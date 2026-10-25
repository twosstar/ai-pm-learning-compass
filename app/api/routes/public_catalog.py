from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Course, KnowledgePoint, Lesson
from app.db.session import get_db
from app.services.public_curriculum import curriculum_sources, public_curriculum

router = APIRouter(prefix="/catalog", tags=["public-curriculum"])
DbSession = Annotated[Session, Depends(get_db)]


def _public_course(db: Session):
    manifest = public_curriculum()
    course = db.get(Course, manifest["course"]["id"])
    if not course or course.start_url != "public://ai-pm-foundations":
        return manifest, None
    return manifest, course


def _valid_lesson(db: Session, definition: dict, course: Course):
    lesson = db.get(Lesson, definition["id"])
    if not lesson or lesson.course_id != course.id or not lesson.url.startswith("public://"):
        return None
    return lesson


def _point_summaries(db: Session, definition: dict) -> list[dict]:
    rows = {point.id: point for point in db.query(KnowledgePoint)
            .filter_by(lesson_id=definition["id"]).all()}
    return [
        {"id": point.id, "name": point.name, "mastery": _mastery(db, point.id)}
        for metadata in definition["knowledge_points"]
        if (point := rows.get(metadata["id"])) is not None
    ]


@router.get("")
def get_catalog(db: DbSession) -> dict:
    """Return course navigation and progress without lesson bodies."""
    manifest, course = _public_course(db)
    lessons = []
    if course:
        for definition in manifest["lessons"]:
            lesson = _valid_lesson(db, definition, course)
            if not lesson:
                continue
            lessons.append({
                "id": lesson.id,
                "number": definition["order"],
                "title": lesson.title,
                "section": lesson.section_title,
                "module_id": definition["module_id"],
                "knowledge_points": _point_summaries(db, definition),
            })
    textbook_lessons = sum(
        any(source["kind"] == "textbook" for source in curriculum_sources(item["source_ids"]))
        for item in manifest["lessons"] if any(lesson["id"] == item["id"] for lesson in lessons)
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


@router.get("/{lesson_id}")
def get_lesson(lesson_id: int, db: DbSession) -> dict:
    """Return one lesson after the learner opens it."""
    manifest, course = _public_course(db)
    definition = next((item for item in manifest["lessons"] if item["id"] == lesson_id), None)
    lesson = _valid_lesson(db, definition, course) if definition and course else None
    if not lesson:
        raise HTTPException(status_code=404, detail="未找到公开课程。")

    rows = {point.id: point for point in db.query(KnowledgePoint).filter_by(lesson_id=lesson.id).all()}
    points = []
    for metadata in definition["knowledge_points"]:
        point = rows.get(metadata["id"])
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
            "teaching_sections": metadata.get("teaching_sections", []),
            "quick_study": metadata.get("quick_study"),
        })
    return {
        "course": {"id": course.id, "name": course.name},
        "lesson": {
            "id": lesson.id,
            "number": definition["order"],
            "title": lesson.title,
            "section": lesson.section_title,
            "module_id": definition["module_id"],
            "summary": definition["content"],
            "objectives": definition["objectives"],
            "practice_task": definition["practice_task"],
            "knowledge_points": points,
        },
    }


def _mastery(db: Session, point_id: int) -> int:
    from app.db.repository import Repository

    result = Repository(db).get_mastery_score(point_id)
    return result.mastery_score if result else 0
