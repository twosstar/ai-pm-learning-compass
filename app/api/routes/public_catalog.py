from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Course, KnowledgePoint, Lesson
from app.db.session import get_db
from app.services.public_curriculum import curriculum_sources, public_curriculum

router = APIRouter(prefix="/catalog", tags=["public-curriculum"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
def get_catalog(db: DbSession) -> dict:
    manifest = public_curriculum()
    course = db.get(Course, manifest["course"]["id"])
    lessons = []
    if course and course.start_url == "public://ai-pm-foundations":
        for definition in manifest["lessons"]:
            lesson = db.get(Lesson, definition["id"])
            if not lesson or lesson.course_id != course.id or not lesson.url.startswith("public://"):
                continue
            point_rows = {point.id: point for point in db.query(KnowledgePoint)
                          .filter_by(lesson_id=lesson.id).all()}
            points = []
            for metadata in definition["knowledge_points"]:
                point = point_rows.get(metadata["id"])
                if point is None:
                    continue
                points.append({
                    "id": point.id,
                    "name": point.name,
                    "category": point.category,
                    "description": point.description,
                    "core_explanation": point.core_explanation,
                    "why_explanation": point.why_explanation,
                    "teaching_example": point.teaching_example,
                    "ai_pm_relevance": point.ai_pm_relevance,
                    "mastery": _mastery(db, point.id),
                    "sources": curriculum_sources(metadata["source_ids"]),
                    "example_basis": metadata["example_basis"],
                    "teaching_sections": metadata.get("teaching_sections", []),
                    "quick_study": metadata.get("quick_study"),
                })
            lessons.append({
                "id": lesson.id,
                "number": definition["order"],
                "title": lesson.title,
                "section": lesson.section_title,
                "module_id": definition["module_id"],
                "summary": definition["content"],
                "objectives": definition["objectives"],
                "practice_task": definition["practice_task"],
                "sources": curriculum_sources(definition["source_ids"]),
                "content_basis": definition["content_basis"],
                "knowledge_points": points,
            })
    textbook_lessons = sum(
        any(source["kind"] == "textbook" for source in lesson["sources"]) for lesson in lessons
    )
    return {
        "items": [{"id": course.id, "name": course.name, "lessons": lessons}] if course and lessons else [],
        "modules": manifest["modules"],
        "total_lessons": len(lessons),
        "total_knowledge_points": sum(len(lesson["knowledge_points"]) for lesson in lessons),
        "textbook_lessons": textbook_lessons,
        "outline_sources": manifest["outline_sources"],
        "editorial_note": manifest["editorial_note"],
        "version": manifest["version"],
    }


def _mastery(db: Session, point_id: int) -> int:
    from app.db.repository import Repository

    result = Repository(db).get_mastery_score(point_id)
    return result.mastery_score if result else 0
