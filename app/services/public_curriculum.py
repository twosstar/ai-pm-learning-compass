"""Curated lesson manifest and provenance, separate from runtime AI output."""
import json
from functools import lru_cache
from pathlib import Path

from app.services.compact_teaching import apply_compact_teaching

CURRICULUM_FILE = Path(__file__).parents[1] / "data" / "public_curriculum.json"


@lru_cache(maxsize=1)
def public_curriculum() -> dict:
    payload = json.loads(CURRICULUM_FILE.read_text(encoding="utf-8"))
    pilot = teaching_pilot()
    lesson = next(item for item in payload['lessons'] if item['id'] == pilot['lesson_id'])
    lesson.update({key: pilot[key] for key in ('content', 'objectives', 'practice_task')})
    for update in pilot['knowledge_points']:
        point = next(item for item in lesson['knowledge_points'] if item['id'] == update['id'])
        point.update(update)
    lesson['teaching_version'] = pilot['version']
    apply_compact_teaching(payload, excluded_lesson=pilot['lesson_id'])
    return payload


@lru_cache(maxsize=1)
def teaching_pilot() -> dict:
    return json.loads((CURRICULUM_FILE.parent / 'lesson102_teaching.json').read_text(encoding='utf-8'))


def lesson_definition(lesson_id: int) -> dict | None:
    return next((lesson for lesson in public_curriculum()["lessons"]
                 if lesson["id"] == lesson_id), None)


def curriculum_sources(source_ids: list[str]) -> list[dict]:
    sources = public_curriculum()["sources"]
    return [dict(sources[source_id], id=source_id) for source_id in source_ids]


def public_point_ids(lesson_id: int) -> set[int]:
    definition = lesson_definition(lesson_id)
    return {point["id"] for point in definition["knowledge_points"]} if definition else set()
