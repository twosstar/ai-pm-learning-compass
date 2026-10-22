import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.db.repository import Repository

DEFAULT_TARGET_ROLE = "general_ai_pm"
PROFILE_PATH = Path(__file__).parents[1] / "config" / "target_roles.json"


class TargetRoleProfile(BaseModel):
    id: str
    name: str
    core_skills: list[str]
    interview_topic_weights: dict[str, int]
    technical_depth_requirement: str
    importance_topic_weights: dict[str, int] = Field(default_factory=dict)
    case_focus: list[str]
    project_focus: list[str]
    question_category_weights: dict[str, float] = Field(default_factory=dict)


def _load_profiles() -> dict[str, TargetRoleProfile]:
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profiles = [TargetRoleProfile.model_validate(item) for item in raw]
    return {profile.id: profile for profile in profiles}


PROFILES = _load_profiles()

TOPIC_KEYWORDS = {
    "Agent Memory": ("agent memory", "智能体记忆", "长期记忆", "短期记忆"),
    "Tool Calling": ("tool calling", "工具调用", "function calling"),
    "Planning": ("planning", "任务规划", "计划能力"),
    "Agent Architecture": ("agent", "智能体", "multi-agent", "多智能体"),
    "Chunking": ("chunk", "切块", "分块"),
    "Rerank": ("rerank", "重排"),
    "Retrieval": ("retrieval", "召回", "检索"),
    "RAG": ("rag", "知识库", "检索增强"),
    "Recommendation & Ranking": ("推荐", "排序", "ranking", "recommendation"),
    "Feature Engineering": ("特征工程", "feature engineering"),
    "Evaluation": ("评估", "evaluation", "precision", "recall", "准确率", "召回率"),
    "Prompt": ("prompt", "提示词"),
    "Education AI": ("教育", "学习", "教学", "学生", "教师"),
    "Model Training": ("模型训练", "微调", "fine-tuning", "fine tuning"),
    "Machine Learning": (
        "机器学习",
        "回归",
        "决策树",
        "分类",
        "聚类",
        "算法",
        "sigmoid",
    ),
    "Safety": ("安全", "隐私", "合规", "越狱", "内容审核"),
    "LLM Applications": ("llm", "大模型", "生成式", "文生文"),
}


class TargetRoleService:
    @staticmethod
    def list_profiles() -> list[TargetRoleProfile]:
        return list(PROFILES.values())

    @staticmethod
    def get_profile(role_id: str | None) -> TargetRoleProfile:
        return PROFILES.get(role_id or DEFAULT_TARGET_ROLE, PROFILES[DEFAULT_TARGET_ROLE])

    def selected_profile(self, repository: Repository) -> TargetRoleProfile:
        return self.get_profile(repository.get_target_role())

    @staticmethod
    def infer_topic(name: str, category: str) -> str:
        text = f"{name} {category}".casefold()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return topic
        return "Product Design"

    def relevance(self, profile: TargetRoleProfile, point) -> int:
        topic = self.infer_topic(point.name, point.category)
        return max(1, min(5, profile.interview_topic_weights.get(topic, 2)))

    def requires_p2(self, profile: TargetRoleProfile, point) -> bool:
        return profile.technical_depth_requirement == "P2" and self.relevance(profile, point) >= 4

    def point_readiness(
        self, repository: Repository, point, profile: TargetRoleProfile | None = None
    ) -> tuple[int, bool]:
        profile = profile or self.selected_profile(repository)
        mastery = repository.get_mastery_score(point.id)
        if not mastery:
            return 0, False
        base_score = mastery.interview_readiness
        if not self.requires_p2(profile, point):
            return base_score, mastery.interview_ready
        p2_scores = [
            score
            for attempt, score in repository.attempts_with_scores(point.id)
            if attempt.interview_depth == "P2"
        ]
        p2_score = p2_scores[-1] if p2_scores else 0
        adjusted = round(0.75 * base_score + 0.25 * p2_score)
        # P2 affects the role-specific aggregate score, but never blocks progress after a valid PASS.
        return adjusted, mastery.interview_ready

    def page_readiness(
        self,
        repository: Repository,
        lesson_id: int,
        profile: TargetRoleProfile | None = None,
    ) -> int:
        profile = profile or self.selected_profile(repository)
        points = [
            point
            for point in repository.list_knowledge_points(lesson_id)
            if point.interview_depth != "P3"
        ]
        if not points:
            return 0
        weighted_sum = 0
        total_weight = 0
        for point in points:
            readiness, _ = self.point_readiness(repository, point, profile)
            weight = max(1, point.interview_value * self.relevance(profile, point))
            weighted_sum += readiness * weight
            total_weight += weight
        return round(weighted_sum / total_weight)


target_role_service = TargetRoleService()
