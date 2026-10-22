from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class GoalRecommendRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    target_role: str = Field(default="general_ai_pm", max_length=60)


class GoalRecommendation(BaseModel):
    course_id: int
    course_name: str
    lesson_id: int
    lesson_title: str
    chapter_title: str = ""
    section_title: str = ""
    knowledge_point_ids: list[int] = Field(default_factory=list)
    knowledge_point_names: list[str] = Field(default_factory=list)
    relevance_score: int = Field(ge=0, le=100)
    recommendation: str = "INCLUDE"
    reason: str = ""


class GoalRecommendations(BaseModel):
    items: list[GoalRecommendation]


class GoalSourceSelection(BaseModel):
    course_id: int
    lesson_ids: list[int] = Field(default_factory=list)
    knowledge_point_ids: list[int] = Field(default_factory=list)
    relevance_score: float = Field(default=0, ge=0, le=100)
    selection_source: str = "MANUAL"


class GoalBuildRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    target_role: str = Field(default="general_ai_pm", max_length=60)
    target_readiness: int = Field(default=60, ge=0, le=100)
    daily_minutes: int = Field(default=30, ge=5, le=1440)
    deadline: date | None = None
    creation_mode: Literal["AI_RECOMMENDED", "MANUAL"]
    sources: list[GoalSourceSelection] = Field(min_length=1, max_length=100)


class ReorderUnitsRequest(BaseModel):
    unit_ids: list[int] = Field(min_length=1)


class LearningGoalIncrementalCompileRequest(BaseModel):
    course_ids: list[int] = Field(min_length=1, max_length=100)


class LearningUnitView(BaseModel):
    id: int
    title: str
    capability_tags: list[str] = Field(default_factory=list)
    unit_type: str
    phase_index: int = 0
    phase_label: str = ""
    aggregation_type: str = "STANDALONE_UNIT"
    merge_type: str
    canonical_topic_id: str = ""
    summary: str = ""
    learning_objective: str = ""
    importance: int = 3
    goal_relevance: float = 0
    difficulty: int = 1
    source_quality: float = 0
    source_section_ids: list[str] = Field(default_factory=list)
    primary_source_id: int | None = None
    supplementary_source_ids: list[int] = Field(default_factory=list)
    estimated_minutes: int = 15
    order_index: int
    primary_knowledge_point_id: int | None = None
    source_course_ids: list[int] = Field(default_factory=list)
    source_lesson_ids: list[int] = Field(default_factory=list)
    source_knowledge_point_ids: list[int] = Field(default_factory=list)
    prerequisite_unit_ids: list[int] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    status: str
    mastery: int
    importance_level: str = "SECONDARY"
    importance_score: float = 3


class LearningGoalView(BaseModel):
    id: int
    name: str
    description: str
    target_role: str
    target_readiness: int = 60
    daily_minutes: int = 30
    deadline: date | None = None
    goal_snapshot: dict = Field(default_factory=dict)
    creation_mode: str
    status: str
    sources: list[dict] = Field(default_factory=list)
    units: list[LearningUnitView] = Field(default_factory=list)
    latest_compile_report: dict | None = None
