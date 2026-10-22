from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    start_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class CrawlProgress(Base):
    __tablename__ = "crawl_progress"

    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    pending_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    visited_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Concept(Base):
    """Locally cached, canonical learning concepts. No lookup reads an LLM."""
    __tablename__ = "concepts"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    category: Mapped[str] = mapped_column(String(60), default="FOUNDATION", index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="COURSE_DISCOVERED", index=True)
    recommended_concept: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    course_coverage_count: Mapped[int] = mapped_column(Integer, default=0)
    recommendation_reason: Mapped[str] = mapped_column(Text, default="")
    course_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    card_status: Mapped[str] = mapped_column(String(30), default="PLACEHOLDER", index=True)
    short_definition: Mapped[str] = mapped_column(Text, default="")
    core_mechanism: Mapped[str] = mapped_column(Text, default="")
    when_to_use: Mapped[str] = mapped_column(Text, default="")
    when_not_to_use: Mapped[str] = mapped_column(Text, default="")
    ai_pm_relevance: Mapped[str] = mapped_column(Text, default="")
    example: Mapped[str] = mapped_column(Text, default="")
    interview_questions_json: Mapped[str] = mapped_column(Text, default="[]")
    concept_type: Mapped[str] = mapped_column(String(60), default="TECH_CONCEPT", index=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    quality_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    concept_value_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    concept_level: Mapped[str] = mapped_column(String(20), default="SUPPLEMENTARY", index=True)
    source_course_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    source_section_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    source_kp_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    concept_version: Mapped[str] = mapped_column(String(30), default="local_v1")
    card_version: Mapped[str] = mapped_column(String(30), default="concept_card_v1")
    card_sections_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConceptQueryCache(Base):
    """Short-lived API previews that have not been promoted to the local library."""
    __tablename__ = "temporary_query_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_query: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(200), default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    category: Mapped[str] = mapped_column(String(60), default="FOUNDATION", index=True)
    concept_level: Mapped[str] = mapped_column(String(20), default="SUPPLEMENTARY", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    api_provider: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    promoted_concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True, index=True
    )


class ConceptScopeMembership(Base):
    """Explicit user/course membership for a concept already in the library."""
    __tablename__ = "concept_scope_memberships"
    __table_args__ = (
        UniqueConstraint("concept_id", "scope_type", "course_id", "section_id", name="uq_concept_scope_membership"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(40), default="ALL_COURSES", index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True)
    section_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    membership_source: Mapped[str] = mapped_column(String(40), default="USER_ADDED", index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PendingConceptRelation(Base):
    """Relations named by a preview whose target is not in the local library yet."""
    __tablename__ = "pending_concept_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    target_name: Mapped[str] = mapped_column(String(200))
    normalized_target_name: Mapped[str] = mapped_column(String(200), index=True)
    relation_type: Mapped[str] = mapped_column(String(30), default="RELATED_TO")
    relation_explanation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    resolved_concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConceptRelation(Base):
    __tablename__ = "concept_relations"
    __table_args__ = (UniqueConstraint("source_concept_id", "target_concept_id", "relation_type", name="uq_concept_relation"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    target_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(30), index=True)
    relation_explanation: Mapped[str] = mapped_column(Text, default="")
    relation_source: Mapped[str] = mapped_column(String(40), default="CANONICAL_KNOWLEDGE", index=True)
    source_course_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("course_id", "url", name="uq_lesson_course_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(10), default="WEB", index=True)
    parser_version: Mapped[str] = mapped_column(String(40), default="legacy_gitbook_v1", index=True)
    structural_integrity: Mapped[str] = mapped_column(String(30), default="UNVERIFIED", index=True)
    migration_status: Mapped[str] = mapped_column(String(30), default="", index=True)
    content_pipeline_version: Mapped[str] = mapped_column(String(40), default="learning_content_v3", index=True)
    source_file: Mapped[str] = mapped_column(Text, default="")
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_title: Mapped[str] = mapped_column(String(500), default="")
    section_title: Mapped[str] = mapped_column(String(500), default="")
    importance_topic: Mapped[str] = mapped_column(String(100), default="Other", index=True)
    base_importance_score: Mapped[int] = mapped_column(Integer, default=-1, index=True)
    interview_value: Mapped[int] = mapped_column(Integer, default=-1)
    practical_product_value: Mapped[int] = mapped_column(Integer, default=-1)
    prerequisite_importance: Mapped[int] = mapped_column(Integer, default=-1)
    base_importance_reason: Mapped[str] = mapped_column(Text, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    course: Mapped[Course] = relationship(back_populates="lessons")


class PDFImport(Base):
    __tablename__ = "pdf_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    text_page_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_page_count: Mapped[int] = mapped_column(Integer, default=0)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="PROCESSING", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    reason_code: Mapped[str] = mapped_column(String(60), default="")
    page_quality_score: Mapped[int] = mapped_column(Integer, default=0)
    section_quality_score: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_quality_score: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    role_level: Mapped[str] = mapped_column(String(100))
    focus: Mapped[str] = mapped_column(String(300), default="综合产品能力")
    history_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# V2 tables are deliberately independent from V1 learning and interview records.
class MechanismMastery(Base):
    __tablename__ = "mechanism_mastery"

    id: Mapped[int] = mapped_column(primary_key=True)
    mechanism_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(40), default="未学习")
    best_level: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MechanismAttempt(Base):
    __tablename__ = "mechanism_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    mechanism_key: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    response: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class V2CaseAttempt(Base):
    __tablename__ = "v2_case_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_key: Mapped[str] = mapped_column(String(80), index=True)
    response: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliverableScore(Base):
    __tablename__ = "deliverable_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    deliverable_type: Mapped[str] = mapped_column(String(60), index=True)
    case_key: Mapped[str] = mapped_column(String(80), default="")
    content: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class V2Progress(Base):
    """Small V2-only settings store; keeps role selection out of V1 data."""
    __tablename__ = "v2_progress"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class V2TrainingAttempt(Base):
    __tablename__ = "v2_training_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[str] = mapped_column(String(100), index=True)
    role_key: Mapped[str] = mapped_column(String(80), index=True)
    mechanism_key: Mapped[str] = mapped_column(String(80), default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    answer: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewImportBatch(Base):
    """One reviewable import operation. Questions can be removed by rolling back the batch."""

    __tablename__ = "interview_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(500))
    source_locator: Mapped[str] = mapped_column(Text, default="")
    input_kind: Mapped[str] = mapped_column(String(30), default="paste")
    source_type: Mapped[str] = mapped_column(String(30), default="local_file", index=True)
    source_cursor: Mapped[int] = mapped_column(Integer, default=0)
    scroll_count: Mapped[int] = mapped_column(Integer, default=0)
    max_questions: Mapped[int] = mapped_column(Integer, default=100)
    stop_reason: Mapped[str] = mapped_column(String(80), default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="preview", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InterviewQuestion(Base):
    """Independent interview bank; course pages remain in the course knowledge tables."""

    __tablename__ = "interview_question_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("interview_import_batches.id", ondelete="RESTRICT"), index=True
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text)
    normalized_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    question_type: Mapped[str] = mapped_column(String(100), index=True)
    topic: Mapped[str] = mapped_column(String(200), index=True)
    difficulty: Mapped[str] = mapped_column(String(30), default="基础", index=True)
    interview_value: Mapped[int] = mapped_column(Integer, default=3, index=True)
    must_have_points_json: Mapped[str] = mapped_column(Text, default="[]")
    follow_ups_json: Mapped[str] = mapped_column(Text, default="[]")
    answer_framework_json: Mapped[str] = mapped_column(Text, default="[]")
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudyRecord(Base):
    __tablename__ = "study_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_lesson_ids: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LessonStudySession(Base):
    __tablename__ = "lesson_study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    key_points_json: Mapped[str] = mapped_column(Text, default="[]")
    history_json: Mapped[str] = mapped_column(Text, default="[]")
    mastery_score: Mapped[int] = mapped_column(Integer, default=0)
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LearningPreference(Base):
    __tablename__ = "learning_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    target_role: Mapped[str] = mapped_column(String(60), default="general_ai_pm")
    learning_goal: Mapped[str] = mapped_column(String(60), default="GENERAL_AI_PM")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LearningGoal(Base):
    __tablename__ = "learning_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    target_role: Mapped[str] = mapped_column(String(60), default="general_ai_pm")
    target_readiness: Mapped[int] = mapped_column(Integer, default=60)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=30)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    goal_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    creation_mode: Mapped[str] = mapped_column(String(30), default="AI_RECOMMENDED")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sources: Mapped[list["GoalSource"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    units: Mapped[list["LearningUnit"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class GoalSource(Base):
    __tablename__ = "goal_sources"
    __table_args__ = (UniqueConstraint("goal_id", "course_id", name="uq_goal_source_course"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    selected_lesson_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    selection_source: Mapped[str] = mapped_column(String(30), default="MANUAL")
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="INCLUDED")
    goal: Mapped[LearningGoal] = relationship(back_populates="sources")


class LearningUnit(Base):
    __tablename__ = "learning_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    # unit_type describes what the learner studies; aggregation_type preserves
    # whether several source points were merged or this remains standalone.
    unit_type: Mapped[str] = mapped_column(String(30), default="CONCEPT", index=True)
    aggregation_type: Mapped[str] = mapped_column(String(30), default="STANDALONE_UNIT", index=True)
    merge_type: Mapped[str] = mapped_column(String(30), default="NONE")
    canonical_topic_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    learning_objective: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[int] = mapped_column(Integer, default=3, index=True)
    goal_relevance: Mapped[float] = mapped_column(Float, default=0)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    source_quality: Mapped[float] = mapped_column(Float, default=0)
    source_section_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    primary_source_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    supplementary_source_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15)
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    primary_knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    source_course_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    source_lesson_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    source_knowledge_point_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    capability_tags_json: Mapped[str] = mapped_column(Text, default="[]")
    prerequisite_unit_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED", index=True)
    mastery: Mapped[int] = mapped_column(Integer, default=0)
    goal: Mapped[LearningGoal] = relationship(back_populates="units")


class LearningGoalCompileReport(Base):
    __tablename__ = "learning_goal_compile_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id", ondelete="CASCADE"), index=True)
    compile_mode: Mapped[str] = mapped_column(String(30), default="FULL", index=True)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", index=True)
    raw_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    container_filtered_count: Mapped[int] = mapped_column(Integer, default=0)
    fragment_filtered_count: Mapped[int] = mapped_column(Integer, default=0)
    noise_filtered_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_topic_count: Mapped[int] = mapped_column(Integer, default=0)
    exact_duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    merged_count: Mapped[int] = mapped_column(Integer, default=0)
    depth_variant_count: Mapped[int] = mapped_column(Integer, default=0)
    kept_separate_count: Mapped[int] = mapped_column(Integer, default=0)
    final_unit_count: Mapped[int] = mapped_column(Integer, default=0)
    cycle_break_count: Mapped[int] = mapped_column(Integer, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    failed_buckets_json: Mapped[str] = mapped_column(Text, default="[]")
    filtered_candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (UniqueConstraint("lesson_id", "name", name="uq_knowledge_point_lesson_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    difficulty: Mapped[str] = mapped_column(String(30), default="基础")
    importance_for_ai_pm: Mapped[int] = mapped_column(Integer, default=3)
    importance_for_interview: Mapped[int] = mapped_column(Integer, default=3)
    prerequisite: Mapped[str] = mapped_column(Text, default="")
    source_page: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str] = mapped_column(Text)
    core_explanation: Mapped[str] = mapped_column(Text, default="")
    why_explanation: Mapped[str] = mapped_column(Text, default="")
    teaching_example: Mapped[str] = mapped_column(Text, default="")
    ai_pm_relevance: Mapped[str] = mapped_column(Text, default="")
    extended_explanation: Mapped[str] = mapped_column(Text, default="")
    interview_depth: Mapped[str] = mapped_column(String(10), default="P1", index=True)
    interview_value: Mapped[int] = mapped_column(Integer, default=3, index=True)
    interview_requirements_json: Mapped[str] = mapped_column(Text, default="[]")
    unnecessary_detail_json: Mapped[str] = mapped_column(Text, default="[]")
    # Grounding and transfer metadata are kept separate from the learner-facing
    # teaching copy so course evidence can never be confused with supplements.
    source_course_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_section_id: Mapped[str] = mapped_column(String(120), default="")
    source_kp_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    required_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    covered_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    coverage_gap_json: Mapped[str] = mapped_column(Text, default="[]")
    mechanism_chain_json: Mapped[str] = mapped_column(Text, default="[]")
    trigger_signals_json: Mapped[str] = mapped_column(Text, default="[]")
    tradeoff_compare_json: Mapped[str] = mapped_column(Text, default="[]")
    application_bridge_json: Mapped[str] = mapped_column(Text, default="{}")
    transfer_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    importance_topic: Mapped[str] = mapped_column(String(100), default="Other", index=True)
    base_importance_score: Mapped[int] = mapped_column(Integer, default=-1, index=True)
    practical_product_value: Mapped[int] = mapped_column(Integer, default=-1)
    prerequisite_importance: Mapped[int] = mapped_column(Integer, default=-1)
    base_importance_reason: Mapped[str] = mapped_column(Text, default="")
    level_1: Mapped[str] = mapped_column(Text)
    level_2_json: Mapped[str] = mapped_column(Text, default="{}")
    level_3_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ImportanceRating(Base):
    __tablename__ = "importance_ratings"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "learning_goal",
            "target_role",
            name="uq_importance_entity_context",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    learning_goal: Mapped[str] = mapped_column(String(60), index=True)
    target_role: Mapped[str] = mapped_column(String(60), index=True)
    dynamic_importance_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    dynamic_importance_raw: Mapped[float] = mapped_column(Float, default=0)
    priority_label: Mapped[str] = mapped_column(String(40), default="SKIPPABLE")
    importance_reason: Mapped[str] = mapped_column(Text, default="")
    learning_priority_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    mastery_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PublicReadingBookmark(Base):
    """Local single-learner reading position, separate from mastery/evaluations."""
    __tablename__ = 'public_reading_bookmarks'

    lesson_id: Mapped[int] = mapped_column(ForeignKey('lessons.id'), primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey('knowledge_points.id'))
    position: Mapped[float] = mapped_column(Float, default=0)
    view: Mapped[str] = mapped_column(String(20), default='reading')
    read_point_ids_json: Mapped[str] = mapped_column(Text, default='[]')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublicAnswerDraft(Base):
    __tablename__ = 'public_answer_drafts'

    attempt_id: Mapped[int] = mapped_column(ForeignKey('question_attempts.id'), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    current_knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    course_summary: Mapped[str] = mapped_column(Text, default="")
    target_role: Mapped[str] = mapped_column(String(60), default="general_ai_pm")
    scope_type: Mapped[str] = mapped_column(String(20), default="LESSON")
    source_pdf_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_id: Mapped[str] = mapped_column(String(120), default="")
    learning_unit_id: Mapped[int | None] = mapped_column(ForeignKey("learning_units.id", ondelete="SET NULL"), nullable=True, index=True)
    knowledge_point_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    mode: Mapped[str] = mapped_column(String(30), default="question")
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    learning_session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), index=True
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    question_type: Mapped[str] = mapped_column(String(50))
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    stage: Mapped[str] = mapped_column(String(30), default="initial")
    question: Mapped[str] = mapped_column(Text)
    assessment_focus_json: Mapped[str] = mapped_column(Text, default="[]")
    interview_category: Mapped[str] = mapped_column(String(60), default="AI技术理解")
    target_role: Mapped[str] = mapped_column(String(60), default="general_ai_pm", index=True)
    interview_value: Mapped[int] = mapped_column(Integer, default=3)
    interview_depth: Mapped[str] = mapped_column(String(10), default="P1", index=True)
    why_interviewer_asks: Mapped[str] = mapped_column(Text, default="")
    must_have_points_json: Mapped[str] = mapped_column(Text, default="[]")
    bonus_points_json: Mapped[str] = mapped_column(Text, default="[]")
    unnecessary_detail: Mapped[str] = mapped_column(Text, default="")
    question_fingerprint_json: Mapped[str] = mapped_column(Text, default="{}")
    user_answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnswerEvaluation(Base):
    __tablename__ = "answer_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("question_attempts.id", ondelete="CASCADE"), unique=True, index=True
    )
    concept_accuracy: Mapped[int] = mapped_column(Integer)
    technical_understanding: Mapped[int] = mapped_column(Integer)
    product_thinking: Mapped[int] = mapped_column(Integer)
    application_scenario: Mapped[int] = mapped_column(Integer)
    communication_structure: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[int] = mapped_column(Integer, index=True)
    correct_points_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_points_json: Mapped[str] = mapped_column(Text, default="[]")
    incorrect_points_json: Mapped[str] = mapped_column(Text, default="[]")
    imprecise_expressions_json: Mapped[str] = mapped_column(Text, default="[]")
    interviewer_followups_json: Mapped[str] = mapped_column(Text, default="[]")
    key_gaps_json: Mapped[str] = mapped_column(Text, default="[]")
    improved_answer: Mapped[str] = mapped_column(Text)
    expert_answer: Mapped[str] = mapped_column(Text)
    answer_framework_json: Mapped[str] = mapped_column(Text, default="[]")
    framework_version: Mapped[int] = mapped_column(Integer, default=2)
    critical_misconception: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_misconception_detail: Mapped[str] = mapped_column(Text, default="")
    weak_concepts_json: Mapped[str] = mapped_column(Text, default="[]")
    weak_reasoning_json: Mapped[str] = mapped_column(Text, default="[]")
    weak_product_application_json: Mapped[str] = mapped_column(Text, default="[]")
    review_later_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Weakness(Base):
    __tablename__ = "weaknesses"
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", "weakness_type", name="uq_weakness_point_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    weakness_type: Mapped[str] = mapped_column(String(300))
    evidence: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    mistake_count: Mapped[int] = mapped_column(Integer, default=1)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_mastery: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class MasteryScore(Base):
    __tablename__ = "mastery_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), unique=True, index=True
    )
    knowledge_coverage: Mapped[int] = mapped_column(Integer, default=0)
    assessment_score: Mapped[int] = mapped_column(Integer, default=0)
    transfer_score: Mapped[int] = mapped_column(Integer, default=0)
    review_stability: Mapped[int] = mapped_column(Integer, default=0)
    mastery_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="未学习")
    p1_core_score: Mapped[int] = mapped_column(Integer, default=0)
    interview_readiness: Mapped[int] = mapped_column(Integer, default=0, index=True)
    interview_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    interview_status: Mapped[str] = mapped_column(String(30), default="NOT_TESTED", index=True)
    interview_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupplementKnowledge(Base):
    """Short system-sourced supplement attached to a course knowledge point."""
    __tablename__ = "supplement_knowledge"
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", "capability_name", "concept_id", name="uq_supplement_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    capability_name: Mapped[str] = mapped_column(String(200), index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="LOCAL_CONCEPT")
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True, index=True)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[str] = mapped_column(String(40), default="supplement_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QuestionSupplementCache(Base):
    """Question-specific, quality-gated supplement cache; never promoted to Concept Hub."""
    __tablename__ = "question_supplement_cache"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_point_id", "question_digest", "capability_name", "version",
            name="uq_question_supplement_cache_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    question_digest: Mapped[str] = mapped_column(String(64), index=True)
    capability_name: Mapped[str] = mapped_column(String(200), index=True)
    learning_need: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="GENERATING", index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="")
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    generation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(String(40), default="question_supplement_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QuestionCapabilityMap(Base):
    """Cached question-to-capability analysis; invalidated by course/KP versions."""
    __tablename__ = "question_capability_map"
    question_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=True, index=True)
    required_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    covered_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    coverage_version: Mapped[str] = mapped_column(String(80), default="coverage_v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewHistory(Base):
    __tablename__ = "review_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    question_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("question_attempts.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    review_type: Mapped[str] = mapped_column(String(30), default="initial")
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIPMSkillScore(Base):
    __tablename__ = "ai_pm_skill_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class InterviewSprint(Base):
    __tablename__ = "interview_sprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_role: Mapped[str] = mapped_column(String(60), index=True)
    learning_goal: Mapped[str] = mapped_column(String(60), default="INTERVIEW_SPRINT", index=True)
    preparation_days: Mapped[int] = mapped_column(Integer)
    total_days: Mapped[int] = mapped_column(Integer, default=14)
    start_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(UTC).date())
    current_day: Mapped[int] = mapped_column(Integer, default=1)
    daily_minutes: Mapped[int] = mapped_column(Integer)
    baseline_readiness: Mapped[int] = mapped_column(Integer, default=0)
    projected_readiness: Mapped[int] = mapped_column(Integer, default=0)
    target_interview_readiness: Mapped[int] = mapped_column(Integer, default=60)
    target_score: Mapped[int] = mapped_column(Integer, default=60)
    current_score: Mapped[int] = mapped_column(Integer, default=0)
    estimated_required_minutes: Mapped[int] = mapped_column(Integer, default=0)
    skipped_ready_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    highest_risks_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    tasks: Mapped[list["InterviewSprintTask"]] = relationship(
        back_populates="sprint", cascade="all, delete-orphan"
    )


class InterviewSprintTask(Base):
    __tablename__ = "interview_sprint_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    sprint_id: Mapped[int] = mapped_column(
        ForeignKey("interview_sprints.id", ondelete="CASCADE"), index=True
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True
    )
    day_number: Mapped[int] = mapped_column(Integer, index=True)
    task_type: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(40), default="knowledge_point")
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_title: Mapped[str] = mapped_column(String(500), default="")
    target_module: Mapped[str] = mapped_column(String(40), default="learning")
    action_label: Mapped[str] = mapped_column(String(80), default="开始学习")
    deep_link: Mapped[str] = mapped_column(String(1000), default="")
    title: Mapped[str] = mapped_column(String(500))
    rationale: Mapped[str] = mapped_column(Text, default="")
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_gain: Mapped[int] = mapped_column(Integer, default=0)
    priority_rank: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    sprint: Mapped[InterviewSprint] = relationship(back_populates="tasks")


class MistakeItem(Base):
    """Unified mistake-book entry; one row per question fingerprint."""

    __tablename__ = "mistake_items"
    __table_args__ = (UniqueConstraint("question_fingerprint", name="uq_mistake_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("question_attempts.id", ondelete="SET NULL"), nullable=True, index=True)
    question_fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), default="SMART_LEARNING", index=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    topic: Mapped[str] = mapped_column(String(200), default="")
    target_role: Mapped[str] = mapped_column(String(60), default="general_ai_pm")
    question_type: Mapped[str] = mapped_column(String(50), default="")
    latest_score: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="UNRESOLVED", index=True)
    first_wrong_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    latest_user_answer: Mapped[str] = mapped_column(Text, default="")
    evaluation_json: Mapped[str] = mapped_column(Text, default="{}")
    dynamic_importance: Mapped[int] = mapped_column(Integer, default=0)
