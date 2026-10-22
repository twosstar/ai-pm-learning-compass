import json

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.migrations import ensure_schema_compatibility
from app.db.models import (
    AnswerEvaluation,
    Course,
    KnowledgePoint,
    LearningSession,
    Lesson,
    MasteryScore,
    QuestionAttempt,
    ReviewHistory,
    Weakness,
)
from app.db.repository import Repository
from app.db.session import Base
from app.schemas.learning import (
    AnswerEvaluationOutput,
    ExtractedKnowledgePoint,
    GeneratedQuestion,
    KnowledgeExtractionOutput,
    MasteryLoopFeedback,
    MasteryLoopStarted,
    RemediationOutput,
    TutorExpansionOutput,
    WeaknessFinding,
)
from app.services import study as study_module


def test_additive_migration_preserves_existing_learning_tables():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE knowledge_points (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE learning_sessions (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE question_attempts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE mastery_scores (id INTEGER PRIMARY KEY)"))
    ensure_schema_compatibility(engine)
    inspector = inspect(engine)
    learning_columns = {column["name"] for column in inspector.get_columns("learning_sessions")}
    question_columns = {column["name"] for column in inspector.get_columns("question_attempts")}
    point_columns = {column["name"] for column in inspector.get_columns("knowledge_points")}
    mastery_columns = {column["name"] for column in inspector.get_columns("mastery_scores")}
    assert "course_summary" in learning_columns
    assert "target_role" in learning_columns
    assert {"learning_unit_id", "knowledge_point_ids_json"} <= learning_columns
    assert "assessment_focus_json" in question_columns
    assert {
        "core_explanation",
        "why_explanation",
        "teaching_example",
        "ai_pm_relevance",
        "interview_depth",
        "interview_value",
    } <= point_columns
    assert {
        "interview_depth",
        "interview_value",
        "must_have_points_json",
        "target_role",
    } <= question_columns
    assert {"p1_core_score", "interview_readiness", "interview_ready"} <= mastery_columns


def teaching_point() -> ExtractedKnowledgePoint:
    return ExtractedKnowledgePoint(
        name="分类阈值",
        description="分类阈值把概率转为业务类别。",
        category="Machine Learning",
        difficulty="进阶",
        importance_for_ai_pm=5,
        importance_for_interview=4,
        prerequisite="概率与二分类",
        core_explanation="分类阈值是把模型输出的概率转成类别的决策线。之所以需要它，是因为不同业务对误报和漏报的代价不同，不能总把0.5当作固定答案。",
        teaching_example="在欺诈识别中，把阈值从0.5降到0.3，会拦住更多可疑交易，但也可能误拦更多正常用户。",
        ai_pm_relevance="AI产品经理需要结合业务损失与用户体验选择阈值，并通过线上指标持续校准，而不是只比较模型准确率。",
    )


class FakeStructuredLLM:
    def __init__(self) -> None:
        self.evaluation_count = 0

    async def complete_structured(self, schema, system, user, fallback, retries=2, **kwargs):
        if schema is KnowledgeExtractionOutput:
            return KnowledgeExtractionOutput(
                course_summary="本页讲解分类阈值。", knowledge_points=[teaching_point()]
            )
        if schema is GeneratedQuestion:
            return GeneratedQuestion(
                question_type="基础定义题",
                difficulty=1,
                question="什么是分类阈值？",
                assessment_focus=["定义", "作用"],
            )
        if schema is RemediationOutput:
            return RemediationOutput(
                mini_lesson="阈值连接概率输出与业务决策。",
                example="风控中可以降低阈值减少漏报。",
                contrast="概率由模型产生，阈值由业务目标决定。",
                retest_question=GeneratedQuestion(
                    question_type="产品应用题",
                    difficulty=2,
                    question="风控产品应如何选择分类阈值？",
                    assessment_focus=["误报", "漏报", "业务成本"],
                ),
            )
        if schema is TutorExpansionOutput:
            return TutorExpansionOutput(
                title="为什么分类阈值需要结合业务设置？",
                content="误报和漏报的业务代价不同 → 同一个概率在不同产品中代表的决策风险不同 → 最优阈值会随业务目标变化。",
            )
        if schema is AnswerEvaluationOutput:
            self.evaluation_count += 1
            if self.evaluation_count == 1:
                return AnswerEvaluationOutput(
                    concept_accuracy=12,
                    technical_understanding=10,
                    product_thinking=10,
                    application_scenario=8,
                    communication_structure=10,
                    correct_points=["知道阈值用于分类"],
                    missing_points=["未说明误报漏报权衡"],
                    incorrect_points=[],
                    imprecise_expressions=["把0.5说成固定规则"],
                    interviewer_followups=["阈值为什么不一定是0.5？"],
                    improved_answer="阈值需结合误报、漏报和业务成本设置。",
                    expert_answer="模型输出概率，产品根据业务代价选择阈值。",
                    answer_framework=["定义", "机制", "业务代价", "案例", "总结"],
                    weaknesses=[
                        WeaknessFinding(
                            weakness_type="classification threshold与业务成本关系不清楚",
                            evidence="用户把0.5当作固定规则",
                            severity="high",
                        )
                    ],
                    next_action="remediate",
                )
            return AnswerEvaluationOutput(
                concept_accuracy=19,
                technical_understanding=18,
                product_thinking=19,
                application_scenario=18,
                communication_structure=18,
                correct_points=["能够结合误报漏报成本选阈值"],
                missing_points=[],
                incorrect_points=[],
                imprecise_expressions=[],
                interviewer_followups=["如何用线上数据持续校准？"],
                improved_answer="根据业务损失函数和验证数据选择阈值。",
                expert_answer="联合验证集指标与误报漏报成本选择并持续校准阈值。",
                answer_framework=["目标", "指标", "成本", "阈值", "监控"],
                weaknesses=[],
                next_action="advance",
            )
        return fallback()


class DecisionTreeTutorLLM(FakeStructuredLLM):
    async def complete_structured(self, schema, system, user, fallback, retries=2, **kwargs):
        if schema is KnowledgeExtractionOutput:
            return KnowledgeExtractionOutput(
                course_summary="本页解释决策树及其过拟合风险。",
                knowledge_points=[
                    ExtractedKnowledgePoint(
                        name="单棵决策树过拟合",
                        description="树过深时容易学习训练数据中的噪声。",
                        category="Machine Learning",
                        difficulty="基础",
                        importance_for_ai_pm=5,
                        importance_for_interview=5,
                        prerequisite="决策树分裂",
                        core_explanation=(
                            "决策树会不断用特征切分训练样本。树太深时，后面的分支可能只是在记住"
                            "少数样本的偶然特征和噪声，而不是可推广的规律，所以训练集表现很好，"
                            "换到新数据上却容易出错。"
                        ),
                        teaching_example=(
                            "例如，贷款模型因为训练集中某位违约用户使用特定手机壳，就继续分裂出"
                            "‘手机壳颜色’规则；它记住了偶然现象，却无法判断新的贷款用户。"
                        ),
                        ai_pm_relevance=(
                            "AI PM需要识别训练效果好但线上效果差的风险，并在模型选择时关注树深、"
                            "验证集表现和可解释性，而不是只看训练准确率。"
                        ),
                    )
                ],
            )
        if schema is GeneratedQuestion:
            return GeneratedQuestion(
                question_type="原理理解题",
                difficulty=1,
                question="请用自己的话解释，为什么单棵决策树容易过拟合？",
                assessment_focus=["持续分裂", "学习噪声", "泛化能力"],
            )
        return await super().complete_structured(
            schema, system, user, fallback, retries=retries, **kwargs
        )


async def test_mastery_loop_persists_remediation_retest_and_calculated_score(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="机器学习", start_url="https://example.com/course")
        db.add(course)
        db.flush()
        lesson = Lesson(
            course_id=course.id,
            title="逻辑回归",
            url="https://example.com/logistic",
            content="逻辑回归输出概率，分类阈值需要结合误报与漏报成本设置。" * 20,
            content_hash="hash",
        )
        db.add(lesson)
        db.commit()
        monkeypatch.setattr(study_module, "llm_service", FakeStructuredLLM())

        started = await study_module.study_service.start_mastery_loop(db, lesson.id)
        MasteryLoopStarted(**started)
        assert started["current_knowledge_point"]["name"] == "分类阈值"
        assert started["question"]["target_role"] == "general_ai_pm"

        first = await study_module.study_service.answer_mastery_question(
            db, started["session_id"], started["question_attempt_id"], "大于0.5就是正类。"
        )
        assert first["total_score"] == 50
        assert first["next_action"] == "probe"
        assert first["remediation"] is None
        assert first["retest_message"]
        assert first["weaknesses"][0]["knowledge_point_id"]
        assert first["framework_version"] == 2
        assert first["framework_generation_status"] in {"READY", "FRAMEWORK_GENERATION_FAILED"}
        saved_evaluation = db.scalar(select(AnswerEvaluation).where(AnswerEvaluation.total_score == 50))
        assert saved_evaluation and saved_evaluation.framework_version == 2
        assert json.loads(saved_evaluation.key_gaps_json)

        second = await study_module.study_service.answer_mastery_question(
            db,
            started["session_id"],
            first["next_attempt_id"],
            "结合误报、漏报的业务损失和验证集指标选择阈值，并持续监控。",
        )
        assert second["total_score"] == 92
        assert second["next_action"] == "interview_ready"
        assert second["interview_ready"] is True
        assert second["interview_readiness"] >= 60
        MasteryLoopFeedback(**second)
        assert second["mastery_status"] == "熟练"

        completed = await study_module.study_service.continue_mastery_loop(
            db, started["session_id"]
        )
        assert completed["completed"] is True
        assert db.scalar(select(func.count(KnowledgePoint.id))) == 1
        assert db.scalar(select(func.count(QuestionAttempt.id))) == 2
        assert db.scalar(select(func.count(AnswerEvaluation.id))) == 2
        assert db.scalar(select(func.count(ReviewHistory.id))) == 2
        assert db.scalar(select(func.count(LearningSession.id))) == 1
        mastery = db.scalar(select(MasteryScore))
        assert mastery and mastery.interview_ready is True
        weakness = db.scalar(select(Weakness))
        assert weakness and weakness.resolved is True


async def test_switching_knowledge_point_creates_a_new_traceable_question(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="机器学习", start_url="https://example.com/course")
        db.add(course)
        db.flush()
        lesson = Lesson(
            course_id=course.id,
            title="模型评估",
            url="https://example.com/evaluation",
            content="分类阈值、精确率和召回率。" * 20,
            content_hash="evaluation",
        )
        db.add(lesson)
        db.commit()
        second_point = teaching_point().model_copy(
            update={"name": "召回率", "description": "召回率衡量正类被找回的比例。"}
        )
        points = Repository(db).replace_knowledge_points(
            lesson, [teaching_point(), second_point]
        )
        monkeypatch.setattr(study_module, "llm_service", FakeStructuredLLM())

        started = await study_module.study_service.start_mastery_loop(db, lesson.id)
        switched = await study_module.study_service.switch_mastery_knowledge_point(
            db, started["session_id"], points[1].id
        )

        assert switched["current_knowledge_point"]["id"] == points[1].id
        attempt = db.get(QuestionAttempt, switched["question_attempt_id"])
        assert attempt and attempt.knowledge_point_id == points[1].id
        assert attempt.stage == "switch"
        session = db.get(LearningSession, started["session_id"])
        assert session and session.current_knowledge_point_id == points[1].id


async def test_compact_tutor_and_on_demand_expansion(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(name="机器学习", start_url="https://example.com/course")
        db.add(course)
        db.flush()
        lesson = Lesson(
            course_id=course.id,
            title="决策树",
            url="https://example.com/tree",
            content="单棵决策树可以持续分裂训练数据，树过深时会学习噪声并导致过拟合。" * 20,
            content_hash="tree",
        )
        db.add(lesson)
        db.commit()
        monkeypatch.setattr(study_module, "llm_service", DecisionTreeTutorLLM())

        started = await study_module.study_service.start_mastery_loop(db, lesson.id)
        point = started["current_knowledge_point"]
        default_teaching = "".join(
            [
                point["core_explanation"],
                point["why_explanation"],
                point["teaching_example"],
                point["ai_pm_relevance"],
            ]
        )
        assert len(default_teaching) <= 500
        assert point["core_explanation"]
        assert point["teaching_example"]
        assert point["ai_pm_relevance"]
        assert started["question"]["question"] == "请用自己的话解释，为什么单棵决策树容易过拟合？"

        expansion = await study_module.study_service.expand_tutor_content(
            db,
            started["session_id"],
            point["id"],
            "why",
            None,
            [],
        )
        assert "→" in expansion["content"]

        deep_dive = await study_module.study_service.deepen_mastery_loop(
            db, started["session_id"]
        )
        assert deep_dive["question"]["interview_depth"] == "P3"
        assert deep_dive["question"]["interview_category"] == "纯算法细节"
