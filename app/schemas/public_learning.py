"""Response models containing only fields required by the public learning UI."""

from pydantic import BaseModel, Field

from app.schemas.learning import (
    InterviewDepth,
    MasteryLoopFeedback,
    QuestionType,
)


class PublicGeneratedQuestion(BaseModel):
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=3)
    question: str
    target_role: str = "general_ai_pm"
    interview_depth: InterviewDepth = "P1"


class PublicCurrentKnowledgePoint(BaseModel):
    id: int
    name: str
    core_explanation: str = ""


class PublicRemediationOutput(BaseModel):
    mini_lesson: str
    example: str
    contrast: str
    retest_question: PublicGeneratedQuestion


class PublicMasteryLoopStarted(BaseModel):
    session_id: int
    lesson_title: str
    course_summary: str
    page_mastery: int
    page_interview_readiness: int
    current_knowledge_point: PublicCurrentKnowledgePoint
    question_attempt_id: int
    question: PublicGeneratedQuestion
    scope_label: str = ""


class PublicMasteryLoopFeedback(MasteryLoopFeedback):
    remediation: PublicRemediationOutput | None = None
    next_question: PublicGeneratedQuestion | None = None


class PublicContinueResponse(BaseModel):
    completed: bool
    session_id: int | None = None
    lesson_id: int | None = None
    lesson_title: str = ""
    scope_label: str = "学习路径"
    course_summary: str = ""
    page_mastery: int = 0
    page_interview_readiness: int = 0
    current_knowledge_point: PublicCurrentKnowledgePoint | None = None
    question_attempt_id: int | None = None
    question: PublicGeneratedQuestion | None = None


def public_question(question) -> dict:
    """Serialize a private rubric-bearing question into the learner-facing shape."""
    if question is None:
        return {}
    values = question.model_dump() if hasattr(question, "model_dump") else dict(question)
    return PublicGeneratedQuestion.model_validate(values).model_dump()
