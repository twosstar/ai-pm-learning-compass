from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal["基础", "进阶", "高级"]
InterviewDepth = Literal["P1", "P2", "P3"]
InterviewCategory = Literal[
    "AI技术理解",
    "技术选型 / Trade-off",
    "产品设计 / Case",
    "LLM / RAG / Agent应用",
    "项目深挖 / Troubleshooting",
    "纯算法细节",
]
QuestionType = Literal[
    "基础定义题",
    "原理理解题",
    "技术对比题",
    "产品应用题",
    "技术选型题",
    "场景Case题",
    "面试题",
]


class TechnicalTeaching(BaseModel):
    principle: str
    workflow: list[str]
    inputs_outputs: str
    formula_or_mechanism: str
    advantages: list[str]
    disadvantages: list[str]
    misconceptions: list[str]
    adjacent_differences: list[str]


class PMTeaching(BaseModel):
    why_ai_pm_needs_it: str
    product_design_impact: str
    model_selection_impact: str
    cost_latency_quality_tradeoff: str
    business_applications: list[str]


class ExtractedKnowledgePoint(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str
    category: str = Field(min_length=1, max_length=100)
    difficulty: Difficulty
    importance_for_ai_pm: int = Field(ge=1, le=5)
    importance_for_interview: int = Field(ge=1, le=5)
    prerequisite: str
    core_explanation: str = Field(min_length=20, max_length=2000)
    why_explanation: str = Field(default="它通过改变信息处理过程和关键约束，最终影响模型或产品结果。", min_length=20, max_length=1200)
    teaching_example: str = Field(min_length=20, max_length=1200)
    ai_pm_relevance: str = Field(min_length=20, max_length=1200)
    extended_explanation: str = Field(default="", max_length=4000)
    interview_depth: InterviewDepth = "P1"
    interview_value: int = Field(default=3, ge=1, le=5)
    interview_requirements: list[str] = Field(default_factory=list, max_length=8)
    unnecessary_detail: list[str] = Field(default_factory=list, max_length=6)


class KnowledgeExtractionOutput(BaseModel):
    course_summary: str
    knowledge_points: list[ExtractedKnowledgePoint] = Field(min_length=1, max_length=10)


class CompactTeachingItem(BaseModel):
    name: str
    core_explanation: str = Field(min_length=20, max_length=2000)
    why_explanation: str = Field(default="它通过改变信息处理过程和关键约束，最终影响模型或产品结果。", min_length=20, max_length=1200)
    teaching_example: str = Field(min_length=20, max_length=1200)
    ai_pm_relevance: str = Field(min_length=20, max_length=1200)
    extended_explanation: str = Field(default="", max_length=4000)
    interview_depth: InterviewDepth = "P1"
    interview_value: int = Field(default=3, ge=1, le=5)
    interview_requirements: list[str] = Field(default_factory=list, max_length=8)
    unnecessary_detail: list[str] = Field(default_factory=list, max_length=6)


class CompactTeachingBatchOutput(BaseModel):
    items: list[CompactTeachingItem] = Field(min_length=1, max_length=20)


class QuestionFingerprint(BaseModel):
    knowledge_point: str = ""
    question_type: str = ""
    tested_skill: str = "technical_reasoning"
    scenario: str = "concept_explanation"
    reasoning_target: str = "explain_core_mechanism"
    expected_answer_dimensions: list[str] = Field(default_factory=list, max_length=8)


class GeneratedQuestion(BaseModel):
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=3)
    question: str = Field(min_length=2)
    assessment_focus: list[str] = Field(min_length=1, max_length=6)
    interview_category: InterviewCategory = "AI技术理解"
    target_role: str = "general_ai_pm"
    interview_value: int = Field(default=3, ge=1, le=5)
    interview_depth: InterviewDepth = "P1"
    why_interviewer_asks: str = "用于判断候选人是否真正理解并能形成产品判断。"
    must_have_points: list[str] = Field(default_factory=list, max_length=8)
    bonus_points: list[str] = Field(default_factory=list, max_length=6)
    unnecessary_detail: str = "题目未要求的数学推导或代码实现不属于必答内容。"
    question_fingerprint: QuestionFingerprint = Field(default_factory=QuestionFingerprint)


class WeaknessFinding(BaseModel):
    weakness_type: str = Field(min_length=2, max_length=300)
    evidence: str
    severity: Literal["low", "medium", "high"]


class AnswerKeyGap(BaseModel):
    point: str = Field(min_length=1, max_length=300)
    why_it_matters: str = Field(min_length=1, max_length=500)
    direction: str = Field(min_length=1, max_length=500)


class AnswerEvaluationOutput(BaseModel):
    evaluation_source: Literal['model', 'offline'] = 'model'
    concept_accuracy: int = Field(ge=0, le=20)
    technical_understanding: int = Field(ge=0, le=20)
    product_thinking: int = Field(ge=0, le=20)
    application_scenario: int = Field(ge=0, le=20)
    communication_structure: int = Field(ge=0, le=20)
    correct_points: list[str] = Field(default_factory=list, max_length=8)
    missing_points: list[str] = Field(default_factory=list, max_length=8)
    incorrect_points: list[str] = Field(default_factory=list, max_length=8)
    imprecise_expressions: list[str] = Field(default_factory=list, max_length=8)
    interviewer_followups: list[str] = Field(default_factory=list, max_length=5)
    key_gaps: list[AnswerKeyGap] = Field(default_factory=list, max_length=3)
    improved_answer: str
    expert_answer: str
    answer_framework: list[str] = Field(default_factory=list, max_length=6)
    weaknesses: list[WeaknessFinding] = Field(default_factory=list, max_length=6)
    critical_misconception: bool = False
    critical_misconception_detail: str = ""
    weak_concepts: list[str] = Field(default_factory=list, max_length=6)
    weak_reasoning: list[str] = Field(default_factory=list, max_length=6)
    weak_product_application: list[str] = Field(default_factory=list, max_length=6)
    review_later: list[str] = Field(default_factory=list, max_length=8)
    next_action: Literal["advance", "probe", "remediate"]
    answer_level: Literal["未达标", "可用", "较好", "优秀"] = "可用"
    score_explanation: str = Field(default="", max_length=500)
    next_level_gap: str = Field(default="", max_length=500)

    @property
    def total_score(self) -> int:
        return (
            self.concept_accuracy
            + self.technical_understanding
            + self.product_thinking
            + self.application_scenario
            + self.communication_structure
        )


class RemediationOutput(BaseModel):
    mini_lesson: str
    example: str
    contrast: str
    retest_question: GeneratedQuestion


class KnowledgeQAOutput(BaseModel):
    direct_answer: str = Field(min_length=1, max_length=600)
    course_points: list[str] = Field(default_factory=list, max_length=5)
    general_supplement: list[str] = Field(default_factory=list, max_length=5)
    boundary_note: str = Field(default="", max_length=300)


ExpansionMode = Literal["simpler", "why", "example", "technical", "compare", "interview"]


class TutorExpansionRequest(BaseModel):
    session_id: int
    knowledge_point_id: int
    mode: ExpansionMode
    compare_concept: str = Field(default="", max_length=200)
    previous_content: list[str] = Field(default_factory=list, max_length=3)


class TutorExpansionOutput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=10, max_length=4000)


class DimensionScores(BaseModel):
    concept_accuracy: int
    technical_understanding: int
    product_thinking: int
    application_scenario: int
    communication_structure: int


class KnowledgePointView(BaseModel):
    id: int
    name: str
    description: str
    category: str
    difficulty: str
    importance_for_ai_pm: int
    importance_for_interview: int
    prerequisite: str
    source_page: str
    source_url: str
    core_explanation: str
    why_explanation: str
    teaching_example: str
    ai_pm_relevance: str
    extended_explanation: str = ""
    interview_depth: InterviewDepth
    interview_value: int
    interview_requirements: list[str]
    unnecessary_detail: list[str]
    mastery_score: int = 0
    mastery_status: str = "未学习"
    interview_readiness: int = 0
    interview_ready: bool = False
    dynamic_importance_score: int = 0
    importance_label: str = "SKIPPABLE"
    importance_label_cn: str = "可忽略"
    importance_reason: str = ""
    learning_priority_score: float = 0
    interview_status: Literal["NOT_TESTED", "LEARNING", "PASS", "NEEDS_REVIEW"] = "NOT_TESTED"
    source_evidence: list[dict] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    covered_capabilities: list[str] = Field(default_factory=list)
    coverage_gap: list[str] = Field(default_factory=list)
    mechanism_chain: list[str] = Field(default_factory=list)
    trigger_signals: list[str] = Field(default_factory=list)
    tradeoff_compare: list[dict] = Field(default_factory=list)
    application_bridge: dict = Field(default_factory=dict)
    supplements: list[dict] = Field(default_factory=list)
    supplement_status: Literal["NOT_NEEDED", "GENERATING", "READY", "FAILED"] = "NOT_NEEDED"
    supplemented_count: int = 0
    supplement_failed_count: int = 0
    supplement_cache_hits: int = 0
    supplement_api_calls: int = 0
    supplement_prompt_tokens: int = 0
    supplement_completion_tokens: int = 0


class MasteryBreakdown(BaseModel):
    knowledge_coverage: int
    assessment_score: int
    transfer_score: int
    review_stability: int


class WeaknessView(BaseModel):
    id: int
    knowledge_point_id: int
    weakness_type: str
    evidence: str
    severity: str
    mistake_count: int
    current_mastery: int


class MasteryLoopStarted(BaseModel):
    session_id: int
    lesson_title: str
    course_summary: str
    page_mastery: int
    page_interview_readiness: int
    knowledge_points: list[KnowledgePointView]
    current_knowledge_point: KnowledgePointView
    question_attempt_id: int
    question: GeneratedQuestion
    scope_label: str = ""


class MasteryAnswerRequest(BaseModel):
    session_id: int
    question_attempt_id: int
    answer: str = Field(min_length=1, max_length=10000)


class MasteryLoopFeedback(BaseModel):
    evaluation_source: Literal['model', 'offline'] = 'model'
    evaluated_question: str = ''
    attempt_id: int
    total_score: int | None = Field(ge=0, le=100)
    answer_level: str = "可用"
    score_explanation: str = ""
    next_level_gap: str = ""
    dimensions: DimensionScores | None
    correct_points: list[str]
    missing_points: list[str]
    incorrect_points: list[str]
    imprecise_expressions: list[str]
    interviewer_followups: list[str]
    user_answer: str
    improved_answer: str
    expert_answer: str
    answer_framework: list[str]
    framework_version: int = 2
    framework_generation_status: str = "READY"
    key_gaps: list[AnswerKeyGap] = Field(default_factory=list, max_length=3)
    weaknesses: list[WeaknessView]
    mastery_score: int
    mastery_status: str
    interview_readiness: int
    interview_ready: bool
    interview_message: str
    old_readiness: int = 0
    new_readiness: int = 0
    readiness_delta: int = 0
    pass_status: Literal["PASS", "LEARNING", "NEEDS_REVIEW", "UNASSESSED"]
    pass_label: str
    critical_misconception: bool
    critical_misconception_detail: str
    review_later: list[str]
    retest_message: str = ""
    previous_question_angle: str = ""
    current_question_angle: str = ""
    mastery_breakdown: MasteryBreakdown
    page_mastery: int
    page_interview_readiness: int
    next_action: Literal[
        "advance", "probe", "remediate", "interview_ready", "needs_review", "defer_and_continue", "complete", "retry_evaluation"
    ]
    remediation: RemediationOutput | None = None
    next_attempt_id: int | None = None
    next_question: GeneratedQuestion | None = None


class ContinueRequest(BaseModel):
    session_id: int


class KnowledgePointSwitchRequest(BaseModel):
    session_id: int
    knowledge_point_id: int


class MasteryLoopContinued(BaseModel):
    completed: bool
    current_knowledge_point: KnowledgePointView | None = None
    question_attempt_id: int | None = None
    question: GeneratedQuestion | None = None


class InterviewRecommendation(BaseModel):
    knowledge_point_id: int
    course_id: int
    lesson_id: int
    name: str
    current_score: int
    interview_value: int
    interview_depth: InterviewDepth
    estimated_minutes: int
    missing_to_ready: str
    priority_score: float
    role_relevance: int


class InterviewDashboard(BaseModel):
      target_role: str
      target_role_name: str
      course_mastery: int
      interview_readiness: int
      actual_global_interview_readiness: int = 0
      readiness_status: str = "NOT_READY"
      core_coverage_percent: int = 0
      evidence_confidence: str = "LOW"
      coverage_percent: int
      studied_pages: int
      eligible_pages: int
      ignored_pages: int
      capability_map: list[dict] = Field(default_factory=list)
      capability_growth: list[dict] = Field(default_factory=list)
      capability_overall: float = 0
      completed_units: int = 0
      total_units: int = 0
      today_learning: dict = Field(default_factory=dict)
      recommendations: list[InterviewRecommendation]


class TargetRoleProfileView(BaseModel):
    id: str
    name: str
    core_skills: list[str]
    interview_topic_weights: dict[str, int]
    importance_topic_weights: dict[str, int] = Field(default_factory=dict)
    technical_depth_requirement: str
    case_focus: list[str]
    project_focus: list[str]


class TargetRoleState(BaseModel):
    selected_role: str
    selected_role_name: str
    profiles: list[TargetRoleProfileView]


class TargetRoleUpdateRequest(BaseModel):
    target_role: str


class RoleRecalculatedView(BaseModel):
    page_interview_readiness: int
    knowledge_points: list[KnowledgePointView]
    current_knowledge_point: KnowledgePointView
    question_attempt_id: int | None = None
    question: GeneratedQuestion | None = None


class InterviewSprintCreateRequest(BaseModel):
    preparation_days: int = Field(ge=1, le=90)
    daily_minutes: int = Field(ge=20, le=480)
    target_role: str
    learning_goal: str = "INTERVIEW_SPRINT"
    target_interview_readiness: int = Field(default=60, ge=40, le=100)
    replan: bool = False


class InterviewSprintTaskView(BaseModel):
    id: int
    day_number: int
    task_type: str
    target_type: str = "knowledge_point"
    target_id: str | None = None
    target_title: str = ""
    target_module: str = "learning"
    action_label: str = "开始学习"
    deep_link: str = ""
    knowledge_point_id: int | None
    title: str
    rationale: str
    estimated_minutes: int
    question_count: int
    expected_gain: int
    status: str


class InterviewSprintDayView(BaseModel):
    day_number: int
    total_minutes: int
    readiness_before: int
    readiness_after: int
    tasks: list[InterviewSprintTaskView]


class InterviewSprintView(BaseModel):
    id: int
    target_role: str
    target_role_name: str
    status: str = "ACTIVE"
    learning_goal: str = "INTERVIEW_SPRINT"
    preparation_days: int
    daily_minutes: int
    baseline_readiness: int
    projected_readiness: int
    target_interview_readiness: int = 60
    score_gap: int = 0
    estimated_required_minutes: int = 0
    start_date: str | None = None
    total_days: int = 14
    current_day: int = 1
    remaining_days: int = 14
    current_score: int = 0
    target_score: int = 60
    actual_global_interview_readiness: int = 0
    sprint_start_readiness: int = 0
    estimated_end_readiness: int = 0
    planned_gain: int = 0
    sprint_phase: str = "FOUNDATION_SPRINT"
    needs_replan: bool = False
    highest_risks: list[str]
    skipped_interview_ready: int
    days: list[InterviewSprintDayView]
