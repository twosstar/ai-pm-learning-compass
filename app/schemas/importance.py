from pydantic import BaseModel, Field


class ImportanceStaticEvaluation(BaseModel):
    base_importance_score: int = Field(ge=0, le=5)
    interview_value: int = Field(ge=0, le=5)
    practical_product_value: int = Field(ge=0, le=5)
    prerequisite_importance: int = Field(ge=0, le=5)
    topic: str
    reason: str


class LearningGoalProfileView(BaseModel):
    id: str
    name: str


class ImportanceContextUpdate(BaseModel):
    learning_goal: str
    target_role: str


class ImportanceContextView(BaseModel):
    learning_goal: str
    learning_goal_name: str
    target_role: str
    target_role_name: str
    learning_goals: list[LearningGoalProfileView]


class ImportanceItemView(BaseModel):
    entity_type: str
    entity_id: int
    page_id: int
    course_id: int
    page_title: str
    chapter_title: str
    section_title: str
    source_url: str
    knowledge_point_name: str = ""
    importance_topic: str
    base_importance_score: int = Field(ge=0, le=5)
    dynamic_importance_score: int = Field(ge=0, le=5)
    dynamic_importance_raw: float
    priority_label: str
    priority_label_cn: str
    importance_reason: str
    learning_priority_score: float
    mastery_score: int
    interview_value: int
    practical_product_value: int
    prerequisite_importance: int
    minimum_interview_path: bool = False


class ImportanceListView(BaseModel):
    learning_goal: str
    learning_goal_name: str
    target_role: str
    target_role_name: str
    total: int
    items: list[ImportanceItemView]
    cached: bool = False


class ImportanceBackfillView(BaseModel):
    lessons_total: int
    lessons_static_created: int
    knowledge_points_total: int
    knowledge_points_static_created: int
    ratings_updated: int
    ratings_reused: int = 0
    cache_hit: bool = False
