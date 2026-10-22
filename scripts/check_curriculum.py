"""Offline content/provenance checks; does not certify source accuracy."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def curriculum_failures(payload: dict | None = None) -> list[str]:
    if payload is None:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.services.public_curriculum import public_curriculum
        payload = public_curriculum()
    issues = []
    lessons = payload["lessons"]
    sources = payload["sources"]
    point_ids = []
    if len(lessons) < 60:
        issues.append("public curriculum must contain at least 60 lessons")
    lesson_ids = [lesson["id"] for lesson in lessons]
    if len(lesson_ids) != len(set(lesson_ids)):
        issues.append("duplicate public lesson IDs")
    module_ids = [value for module in payload["modules"] for value in module["lesson_ids"]]
    if sorted(module_ids) != sorted(lesson_ids):
        issues.append("module membership must cover each lesson exactly once")
    for key, source in sources.items():
        url = urlparse(source["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            issues.append(f"unsafe source locator: {key}")
        if source["kind"] not in {"textbook", "guide", "official_doc", "author_summary", "research_paper"}:
            issues.append(f"unsupported source type: {key}")
        if not source.get("section") or not source.get("edition"):
            issues.append(f"missing source section/version: {key}")
    textbook_lessons = 0
    for lesson in lessons:
        if len(lesson["knowledge_points"]) < 2 or not lesson.get("practice_task") or not lesson.get("objectives"):
            issues.append(f"incomplete lesson: {lesson['id']}")
        if not lesson.get("source_ids") or any(key not in sources for key in lesson["source_ids"]):
            issues.append(f"missing lesson source: {lesson['id']}")
        elif any(sources[key]["kind"] == "textbook" for key in lesson["source_ids"]):
            textbook_lessons += 1
        for point in lesson["knowledge_points"]:
            point_ids.append(point["id"])
            for field, minimum in (("core_explanation", 40), ("why_explanation", 12), ("teaching_example", 15), ("ai_pm_relevance", 12)):
                if len(point.get(field, "").strip()) < minimum:
                    issues.append(f"incomplete {field}: {point['id']}")
            if not point.get("source_ids") or any(key not in lesson["source_ids"] for key in point["source_ids"]):
                issues.append(f"missing point provenance: {point['id']}")
            if not point.get("example_basis"):
                issues.append(f"missing original-example label: {point['id']}")
            quick = point.get('quick_study', {})
            essentials, flow = quick.get('essentials', []), quick.get('flow', [])
            reading = ''.join(essentials) + quick.get('example', '') + quick.get('interview', '')
            if (len(essentials) != 3 or len(flow) not in {4, 5}
                    or any(not node.get('label') or not node.get('owner') for node in flow)
                    or not quick.get('branches') or not quick.get('example') or not quick.get('interview')
                    or len(reading) > 350 or len(point.get('teaching_sections', [])) < 5):
                issues.append(f"incomplete or oversized compact teaching: {point['id']}")
    if len(point_ids) != len(set(point_ids)):
        issues.append("duplicate public knowledge-point IDs")
    if textbook_lessons < len(lessons) / 2:
        issues.append("textbook-backed lessons must remain the majority")
    return issues


if __name__ == "__main__":
    problems = curriculum_failures()
    if problems:
        print("Curriculum check failed:\n" + "\n".join(problems))
        raise SystemExit(1)
    print("Curriculum check passed: lesson content, stable IDs and source metadata are complete.")
