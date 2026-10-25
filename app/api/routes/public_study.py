import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import AnswerEvaluation, KnowledgePoint, LearningSession, Lesson, MistakeItem, QuestionAttempt
from app.db.repository import Repository
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
    review_mode: bool = False


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
            db, payload.session_id, payload.question_attempt_id, payload.answer,
            review_mode=payload.review_mode,
        )
        return MasteryLoopFeedback(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/mistakes")
def list_public_mistakes(db: DbSession) -> dict:
    """Return locally saved, unresolved mistakes from the public curriculum only."""
    repository = Repository(db)
    public_ids = {lesson["id"] for lesson in public_curriculum()["lessons"]}
    repository.backfill_mistakes(lesson_ids=public_ids)
    rows = (
        db.query(MistakeItem, KnowledgePoint, Lesson)
        .join(KnowledgePoint, KnowledgePoint.id == MistakeItem.knowledge_point_id)
        .join(Lesson, Lesson.id == KnowledgePoint.lesson_id)
        .filter(
            MistakeItem.source_type == "SMART_LEARNING",
            MistakeItem.status == "UNRESOLVED",
            Lesson.url.like("public://%"),
            Lesson.id.in_(public_ids),
        )
        .order_by(MistakeItem.last_attempt_at.desc())
        .all()
    )
    items = []
    for mistake, point, lesson in rows:
        evaluation_data = json.loads(mistake.evaluation_json or "{}")
        answer_history = []
        if mistake.question_fingerprint:
            attempts = (
                db.query(QuestionAttempt, AnswerEvaluation)
                .join(AnswerEvaluation, AnswerEvaluation.question_attempt_id == QuestionAttempt.id)
                .join(LearningSession, LearningSession.id == QuestionAttempt.learning_session_id)
                .join(Lesson, Lesson.id == LearningSession.lesson_id)
                .filter(
                    QuestionAttempt.question_fingerprint_json == mistake.question_fingerprint,
                    Lesson.id.in_(public_ids),
                    Lesson.url.like("public://%"),
                )
                .order_by(QuestionAttempt.answered_at.desc(), QuestionAttempt.id.desc())
                .all()
            )
            for attempt, evaluation in attempts:
                answer_history.append({
                    "answer": attempt.user_answer or "",
                    "score": evaluation.total_score,
                    "answered_at": attempt.answered_at.isoformat() if attempt.answered_at else "",
                    "reference_answer": evaluation.expert_answer or evaluation.improved_answer or "",
                })
        if not answer_history and mistake.latest_user_answer:
            answer_history.append({
                "answer": mistake.latest_user_answer,
                "score": mistake.latest_score,
                "answered_at": mistake.last_attempt_at.isoformat() if mistake.last_attempt_at else "",
                "reference_answer": evaluation_data.get("expert_answer") or evaluation_data.get("improved_answer") or "",
            })
        items.append({
            "id": mistake.id,
            "question": mistake.question_text,
            "topic": point.name,
            "lesson_title": lesson.title,
            "latest_score": mistake.latest_score,
            "attempt_count": mistake.attempt_count,
            "last_attempt_at": mistake.last_attempt_at.isoformat() if mistake.last_attempt_at else "",
            "user_answer": mistake.latest_user_answer,
            "reference_answer": evaluation_data.get("expert_answer") or evaluation_data.get("improved_answer") or "",
            "answer_history": answer_history,
        })
    return {"total": len(items), "items": items}


@router.post("/mistakes/{mistake_id}/retry")
def retry_public_mistake(mistake_id: int, db: DbSession) -> dict:
    """Create a separate local practice session for retrying one public mistake."""
    public_ids = {lesson["id"] for lesson in public_curriculum()["lessons"]}
    mistake = db.get(MistakeItem, mistake_id)
    if not mistake or mistake.source_type != "SMART_LEARNING" or mistake.status != "UNRESOLVED":
        raise HTTPException(status_code=404, detail="没有找到这道待复习题目。")
    original = db.get(QuestionAttempt, mistake.question_id) if mistake.question_id else None
    original_session = db.get(LearningSession, original.learning_session_id) if original else None
    point = db.get(KnowledgePoint, original.knowledge_point_id) if original else None
    lesson = db.get(Lesson, point.lesson_id) if point else None
    if not original_session or not point or not lesson or lesson.id not in public_ids or not (lesson.url or "").startswith("public://"):
        raise HTTPException(status_code=404, detail="没有找到这道待复习题目。")
    repository = Repository(db)
    retry_session = repository.create_learning_session(
        lesson_id=lesson.id,
        knowledge_point_id=point.id,
        course_summary=original_session.course_summary,
        target_role=original.target_role,
        scope_type="MISTAKE_REVIEW",
        section_id=original_session.section_id,
        learning_unit_id=original_session.learning_unit_id,
        knowledge_point_ids=[point.id],
    )
    retry_attempt = repository.clone_question_attempt(original, learning_session_id=retry_session.id)
    return {
        "session_id": retry_session.id,
        "lesson_id": lesson.id,
        "lesson_title": lesson.title,
        "course_summary": retry_session.course_summary,
        "current_knowledge_point": {"id": point.id, "name": point.name, "core_explanation": point.core_explanation},
        "question_attempt_id": retry_attempt.id,
        "question": {
            "question": retry_attempt.question,
            "question_type": retry_attempt.question_type,
            "difficulty": retry_attempt.difficulty,
            "assessment_focus": json.loads(retry_attempt.assessment_focus_json or "[]"),
            "interview_category": retry_attempt.interview_category,
            "target_role": retry_attempt.target_role,
            "interview_value": retry_attempt.interview_value,
            "interview_depth": retry_attempt.interview_depth,
            "why_interviewer_asks": retry_attempt.why_interviewer_asks,
            "must_have_points": json.loads(retry_attempt.must_have_points_json or "[]"),
            "bonus_points": json.loads(retry_attempt.bonus_points_json or "[]"),
            "unnecessary_detail": retry_attempt.unnecessary_detail,
        },
        "review_mode": True,
        "evaluated": False,
        "draft_answer": "",
        "can_continue": False,
    }


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
