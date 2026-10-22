from app.db.repository import Repository
from app.services.capability_growth import capability_growth
from app.services.daily_learning import daily_learning_plan
from app.services.readiness import readiness_service
from app.services.target_roles import TargetRoleProfile, target_role_service

QUESTION_DISTRIBUTION = {
    "AI技术理解": 0.20,
    "技术选型 / Trade-off": 0.20,
    "产品设计 / Case": 0.25,
    "LLM / RAG / Agent应用": 0.20,
    "项目深挖 / Troubleshooting": 0.10,
    "纯算法细节": 0.05,
}

QUESTION_TYPE_BY_CATEGORY = {
    "AI技术理解": "原理理解题",
    "技术选型 / Trade-off": "技术选型题",
    "产品设计 / Case": "场景Case题",
    "LLM / RAG / Agent应用": "产品应用题",
    "项目深挖 / Troubleshooting": "面试题",
    "纯算法细节": "原理理解题",
}


def normalized_interview_profile(
    name: str, interview_depth: str, interview_value: int
) -> tuple[str, int]:
    """Keep high-frequency AI PM topics consistent even when model metadata varies."""
    normalized = name.casefold().replace("-", " ").replace("_", " ")
    math_terms = ("推导", "证明", "矩阵计算", "源码实现", "代码实现")
    if any(term in normalized for term in math_terms):
        return "P3", 1
    if "rag" in normalized and any(term in normalized for term in ("fine", "微调")):
        return "P1", 5
    if "agent" in normalized and any(term in normalized for term in ("memory", "记忆")):
        return "P1", 5
    if any(term in normalized for term in ("precision", "recall", "精确率", "召回率")):
        return "P1", 4
    if any(term in normalized for term in ("模型评估", "model evaluation")):
        return "P1", 5
    if any(term in normalized for term in ("决策树", "decision tree")) and "过拟合" in normalized:
        return "P1", 3
    if "attention" in normalized or "注意力机制" in normalized:
        return "P1", 3
    if "sigmoid" in normalized:
        return "P1", 2
    depth = interview_depth if interview_depth in {"P1", "P2", "P3"} else "P1"
    return depth, max(1, min(5, interview_value))


def interview_boundaries(name: str) -> tuple[list[str], list[str]] | None:
    normalized = name.casefold().replace("-", " ").replace("_", " ")
    if any(term in normalized for term in ("决策树", "decision tree")) and "过拟合" in normalized:
        return (
            ["解释为什么树过深会学习噪声", "说明限制树深或剪枝等缓解方法", "解释随机森林为什么更稳"],
            ["Gini系数完整推导", "CART剪枝数学证明", "手写训练代码"],
        )
    if any(term in normalized for term in ("precision", "recall", "精确率", "召回率")):
        return (
            ["说清Precision与Recall分别关注什么", "结合误报漏报成本选指标", "说明阈值变化的影响"],
            ["指标公式证明", "底层评估代码实现"],
        )
    if "rag" in normalized and any(term in normalized for term in ("fine", "微调")):
        return (
            ["根据知识更新频率与任务目标做选型", "比较成本、时效、可控性与效果", "说明可组合使用的场景"],
            ["微调优化器推导", "向量索引底层实现", "训练代码细节"],
        )
    if "agent" in normalized and any(term in normalized for term in ("memory", "记忆")):
        return (
            ["区分短期与长期记忆", "说明写入、检索和遗忘机制", "考虑隐私、错误记忆与产品体验"],
            ["存储引擎源码", "向量数据库索引算法证明"],
        )
    if "attention" in normalized or "注意力机制" in normalized:
        return (
            ["解释模型为何能关注不同信息", "说明它对上下文理解的价值", "知道长上下文的成本与局限"],
            ["Q/K/V矩阵完整推导", "反向传播证明", "底层矩阵计算实现"],
        )
    return None


class InterviewPriorityService:
    def select_question_category(
        self, repository: Repository, profile: TargetRoleProfile | None = None
    ) -> str:
        counts = repository.question_category_counts(profile.id) if profile else repository.question_category_counts()
        next_total = sum(counts.values()) + 1
        weighted = {
            category: ratio * (profile.question_category_weights.get(category, 1.0) if profile else 1.0)
            for category, ratio in QUESTION_DISTRIBUTION.items()
        }
        weight_total = sum(weighted.values())
        return max(
            QUESTION_DISTRIBUTION,
            key=lambda category: (
                next_total * weighted[category] / weight_total - counts.get(category, 0),
                weighted[category],
            ),
        )

    @staticmethod
    def question_depth(
        repository: Repository,
        point,
        category: str,
        profile: TargetRoleProfile,
    ) -> str:
        mastery = repository.get_mastery_score(point.id)
        p1_score = mastery.p1_core_score if mastery else 0
        if target_role_service.requires_p2(profile, point) and p1_score >= 85:
            return "P2"
        if category in {"项目深挖 / Troubleshooting", "纯算法细节"} and p1_score >= 85:
            return "P2"
        return "P1"

    @staticmethod
    def _missing_to_ready(
        repository: Repository, point, profile: TargetRoleProfile
    ) -> str:
        role_score, role_ready = target_role_service.point_readiness(
            repository, point, profile
        )
        if role_ready:
            return "已达到普通AI PM面试要求"
        attempts = repository.attempts_with_scores(point.id)
        gaps: list[str] = []
        valid_attempts = [
            score for attempt, score in attempts if attempt.interview_depth != "P3"
        ]
        if not valid_attempts or valid_attempts[-1] < 60:
            gaps.append("完成1道有效题并达到60分")
        evaluations = repository.attempts_with_evaluations(point.id)
        latest_valid = next(
            (evaluation for attempt, evaluation in reversed(evaluations) if attempt.interview_depth != "P3"),
            None,
        )
        if latest_valid and latest_valid.critical_misconception:
            gaps.append("消除关键概念错误")
        if target_role_service.requires_p2(profile, point):
            p2_scores = [
                score
                for attempt, score in attempts
                if attempt.interview_depth == "P2"
            ]
            if not p2_scores or max(p2_scores) < 60:
                gaps.append(f"可选：补充{profile.name}相关P2能力")
        if role_score < 60 and not gaps:
            gaps.append("补齐目标岗位高权重能力")
        return "；".join(gaps[:3]) or "已合格，非关键遗漏可稍后复习"

    def dashboard(self, repository: Repository, course_id: int | None = None) -> dict:
        profile = target_role_service.selected_profile(repository)
        today_learning = daily_learning_plan(repository.db, profile.id, profile.name)
        points = [
            point
            for point in repository.list_all_knowledge_points(course_id)
            if point.interview_depth != "P3"
        ]
        weighted_readiness = 0
        total_weight = 0
        recommendations = []
        severity_weight = {"low": 0.10, "medium": 0.25, "high": 0.50}
        for point in points:
            lesson = repository.get_lesson(point.lesson_id)
            readiness, role_ready = target_role_service.point_readiness(
                repository, point, profile
            )
            role_relevance = target_role_service.relevance(profile, point)
            weight = max(1, point.interview_value * role_relevance)
            weighted_readiness += readiness * weight
            total_weight += weight
            weaknesses = repository.list_weaknesses(point.id)
            weakness_factor = 1 + (100 - readiness) / 100
            weakness_factor += min(
                0.5, sum(severity_weight.get(item.severity, 0.2) for item in weaknesses)
            )
            normalized_role_relevance = role_relevance / 5
            priority_score = (
                point.interview_value * weakness_factor * normalized_role_relevance
            )
            gap = max(0, 85 - readiness)
            estimated_minutes = 0 if role_ready else 5 if gap <= 10 else 10 if gap <= 30 else 15
            recommendations.append(
                {
                    "knowledge_point_id": point.id,
                    "course_id": lesson.course_id if lesson else 0,
                    "lesson_id": point.lesson_id,
                    "name": point.name,
                    "current_score": readiness,
                    "interview_value": point.interview_value,
                    "interview_depth": point.interview_depth,
                    "estimated_minutes": estimated_minutes,
                    "missing_to_ready": self._missing_to_ready(repository, point, profile),
                    "priority_score": round(priority_score, 2),
                    "role_relevance": role_relevance,
                    "interview_ready": role_ready,
                }
            )
        recommendations.sort(
            key=lambda item: (
                item["interview_ready"],
                -item["priority_score"],
                -item["interview_value"],
            )
        )
        for item in recommendations:
            item.pop("interview_ready")
        return {
            "target_role": profile.id,
            "target_role_name": profile.name,
            **readiness_service.calculate(repository, course_id=course_id),
            **capability_growth(repository.db, profile.id),
            "today_learning": today_learning,
            "recommendations": recommendations[:3],
        }


interview_priority_service = InterviewPriorityService()
