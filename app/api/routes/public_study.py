import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import LearningSession, Lesson, KnowledgePoint
from app.db.session import get_db
from app.schemas.learning import (
    ContinueRequest,
    GeneratedQuestion,
    MasteryLoopFeedback,
    MasteryLoopStarted,
    KnowledgePointView,
)
from app.services.study import study_service
from app.services.public_curriculum import public_curriculum

router = APIRouter(prefix="/study", tags=["smart-learning"])
DbSession = Annotated[Session, Depends(get_db)]


def _include_all_lesson_points(db: Session, result: dict) -> dict:
    """Keep the public session scoped to every point in its lesson."""
    session = db.get(LearningSession, result.get("session_id"))
    points = result.get("knowledge_points") or []
    if session and points:
        session.knowledge_point_ids_json = json.dumps(
            [point["id"] if isinstance(point, dict) else point.id for point in points]
        )
        db.commit()
    return result


class PublicAnswerRequest(BaseModel):
    session_id: int
    question_attempt_id: int
    answer: str = Field(min_length=1, max_length=10000)


class PublicStartRequest(BaseModel):
    lesson_id: int
    target_role: Literal['general_ai_pm', 'ai_education_pm'] | None = None


class PublicContinueResponse(BaseModel):
    completed: bool
    session_id: int | None = None
    lesson_id: int | None = None
    lesson_title: str = ""
    scope_label: str = "学习路径"
    course_summary: str = ""
    page_mastery: int = 0
    page_interview_readiness: int = 0
    knowledge_points: list[KnowledgePointView] = Field(default_factory=list)
    current_knowledge_point: KnowledgePointView | None = None
    question_attempt_id: int | None = None
    question: GeneratedQuestion | None = None


@router.post("/start", response_model=MasteryLoopStarted)
async def start_study(payload: PublicStartRequest, db: DbSession) -> MasteryLoopStarted:
    try:
        lesson = db.get(Lesson, payload.lesson_id)
        if not lesson or not (lesson.url or "").startswith("public://"):
            raise LookupError("未找到公开示例课程。")
        result = await study_service.start_mastery_loop(db, lesson_id=payload.lesson_id, target_role=payload.target_role)
        result = _include_all_lesson_points(db, result)
        return MasteryLoopStarted(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/answer", response_model=MasteryLoopFeedback)
async def answer(payload: PublicAnswerRequest, db: DbSession) -> MasteryLoopFeedback:
    try:
        session = db.get(LearningSession, payload.session_id)
        lesson = db.get(Lesson, session.lesson_id) if session else None
        if not lesson or not (lesson.url or "").startswith("public://"):
            raise LookupError("未找到公开示例课程的学习记录。")
        result = await study_service.answer_mastery_question(
            db, payload.session_id, payload.question_attempt_id, payload.answer
        )
        return MasteryLoopFeedback(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/continue", response_model=PublicContinueResponse)
async def continue_study(payload: ContinueRequest, db: DbSession) -> PublicContinueResponse:
    try:
        active = db.get(LearningSession, payload.session_id)
        current_lesson = db.get(Lesson, active.lesson_id) if active else None
        if not current_lesson or not (current_lesson.url or "").startswith("public://"):
            raise LookupError("未找到公开示例课程的学习记录。")
        result = await study_service.continue_mastery_loop(db, payload.session_id)
        if result.get("completed"):
            next_lesson = None
            if current_lesson:
                next_lesson = (
                    db.query(Lesson)
                    .filter(
                        Lesson.course_id == current_lesson.course_id,
                        Lesson.id > current_lesson.id,
                        Lesson.url.like("public://%"),
                        Lesson.id.in_([item["id"] for item in public_curriculum()["lessons"]]),
                    )
                    .order_by(Lesson.id)
                    .first()
                )
            if not next_lesson:
                return PublicContinueResponse(completed=True)
            result = await study_service.start_mastery_loop(db, lesson_id=next_lesson.id, target_role=active.target_role)
            result = _include_all_lesson_points(db, result)
            result["completed"] = False
            result["lesson_id"] = next_lesson.id
            result["scope_label"] = "下一節"
            return PublicContinueResponse(**result)
        point = result.get("current_knowledge_point")
        point_id = point.get("id") if isinstance(point, dict) else getattr(point, "id", None)
        source_point = db.get(KnowledgePoint, point_id) if point_id else None
        lesson = db.get(Lesson, source_point.lesson_id) if source_point else None
        return PublicContinueResponse(
            **result,
            session_id=payload.session_id,
            lesson_id=lesson.id if lesson else None,
            lesson_title=lesson.title if lesson else "学习路径",
            scope_label="学习路径",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
