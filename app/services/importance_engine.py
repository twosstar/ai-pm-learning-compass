import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import KnowledgePoint, Lesson
from app.db.repository import Repository
from app.services.target_roles import PROFILES

CONFIG_DIR = Path(__file__).parents[1] / "config"

LABELS = {
    5: ("MUST_LEARN", "必学"),
    4: ("HIGH_PRIORITY", "高优先级"),
    3: ("RECOMMENDED", "建议学习"),
    2: ("OPTIONAL", "了解即可"),
    1: ("LOW_PRIORITY", "低优先级"),
    0: ("SKIPPABLE", "可忽略"),
}


class LearningGoalProfile(BaseModel):
    id: str
    name: str
    topic_weights: dict[str, int]


class TopicProfile(BaseModel):
    id: str
    keywords: list[str]
    base_importance: int
    interview_value: int
    practical_product_value: int
    prerequisite_importance: int


def _load(path: str, schema):
    raw = json.loads((CONFIG_DIR / path).read_text(encoding="utf-8"))
    return [schema.model_validate(item) for item in raw]


GOAL_PROFILES = {item.id: item for item in _load("learning_goal_profiles.json", LearningGoalProfile)}
TOPIC_PROFILES = _load("importance_topics.json", TopicProfile)
DEFAULT_GOAL = "GENERAL_AI_PM"


class ImportanceEngine:
    @staticmethod
    def hierarchy(url: str) -> tuple[str, str]:
        parts = [unquote(item) for item in urlparse(url).path.split("/") if item]
        meaningful = [item for item in parts if any("\u4e00" <= char <= "\u9fff" for char in item)]
        if not meaningful:
            return "", ""
        chapter = meaningful[0]
        section = " / ".join(item for item in meaningful[1:] if item != "sources")
        return chapter, section

    @staticmethod
    def infer_topic(name: str, category: str = "", content: str = "") -> TopicProfile:
        primary = f"{name} {category}".casefold()
        fallback = f"{primary} {content[:3000]}".casefold()
        for text in (primary, fallback):
            for topic in TOPIC_PROFILES[:-1]:
                if any(keyword.casefold() in text for keyword in topic.keywords):
                    return topic
        return TOPIC_PROFILES[-1]

    @staticmethod
    def _stars(raw: float) -> int:
        if raw < 0.75:
            return 0
        if raw < 1.5:
            return 1
        if raw < 2.4:
            return 2
        if raw < 3.4:
            return 3
        if raw < 4.2:
            return 4
        return 5

    @staticmethod
    def _mastery_and_weakness(repository: Repository, entity_type: str, entity) -> tuple[int, float]:
        severity = {"low": 0.10, "medium": 0.25, "high": 0.50}
        if entity_type == "knowledge_point":
            mastery = repository.get_mastery_score(entity.id)
            weaknesses = repository.list_weaknesses(entity.id)
            score = mastery.mastery_score if mastery else 0
        else:
            score = repository.page_mastery(entity.id)
            weaknesses = [
                weakness
                for point in repository.list_knowledge_points(entity.id)
                for weakness in repository.list_weaknesses(point.id)
            ]
        weakness_factor = 1 + min(
            0.5, sum(severity.get(item.severity, 0.2) for item in weaknesses if not item.resolved)
        )
        return score, weakness_factor

    def _static_lesson(self, lesson: Lesson) -> bool:
        created = lesson.base_importance_score < 0
        chapter, section = self.hierarchy(lesson.url)
        lesson.chapter_title = lesson.chapter_title or chapter
        lesson.section_title = lesson.section_title or section
        if created:
            topic = self.infer_topic(
                f"{lesson.title} {lesson.chapter_title} {lesson.section_title}", content=lesson.content
            )
            lesson.importance_topic = topic.id
            lesson.base_importance_score = topic.base_importance
            lesson.interview_value = topic.interview_value
            lesson.practical_product_value = topic.practical_product_value
            lesson.prerequisite_importance = topic.prerequisite_importance
            lesson.base_importance_reason = f"该页面属于“{topic.id}”，静态价值已缓存，切换目标时无需重新调用模型。"
        return created

    def _static_point(self, point: KnowledgePoint) -> bool:
        created = point.base_importance_score < 0
        if created:
            topic = self.infer_topic(point.name, point.category, point.description)
            point.importance_topic = topic.id
            point.base_importance_score = topic.base_importance
            point.interview_value = max(0, min(5, point.interview_value or topic.interview_value))
            point.practical_product_value = topic.practical_product_value
            point.prerequisite_importance = topic.prerequisite_importance
            point.base_importance_reason = f"知识点属于“{topic.id}”，基础价值来自缓存的主题元数据。"
        return created

    def calculate_dynamic_importance(
        self, entity, learning_goal: str, target_role: str
    ) -> tuple[float, int, str, str]:
        goal = GOAL_PROFILES[learning_goal]
        role = PROFILES[target_role]
        topic = entity.importance_topic or "Other"
        goal_relevance = goal.topic_weights.get(topic, 2)
        role_relevance = role.importance_topic_weights.get(topic, 2)
        raw = (
            0.20 * entity.base_importance_score
            + 0.25 * goal_relevance
            + 0.25 * role_relevance
            + 0.15 * entity.interview_value
            + 0.10 * entity.practical_product_value
            + 0.05 * entity.prerequisite_importance
        )
        raw = round(max(0, min(5, raw)), 2)
        stars = self._stars(raw)
        label, label_cn = LABELS[stars]
        if stars == 0:
            reason = (
                f"当前目标为“{role.name} + {goal.name}”。该内容偏向{topic}的低相关细节，"
                "本轮可以跳过，不阻塞冲刺完成或最低面试路径。"
            )
        else:
            reason = (
                f"当前目标为“{role.name} + {goal.name}”。该内容属于{topic}；"
                f"目标相关度{goal_relevance}/5、岗位相关度{role_relevance}/5、"
                f"面试价值{entity.interview_value}/5，因此评为{stars}星（{label_cn}）。"
            )
        return raw, stars, label, reason

    def knowledge_point_importance(
        self, point: KnowledgePoint, learning_goal: str, target_role: str
    ) -> int:
        """Return the existing target-aware importance stars for a point."""
        if learning_goal not in GOAL_PROFILES:
            learning_goal = DEFAULT_GOAL
        if target_role not in PROFILES:
            target_role = "general_ai_pm"
        self._static_point(point)
        _, stars, _, _ = self.calculate_dynamic_importance(point, learning_goal, target_role)
        return stars

    def goal_aware_point_importance(
        self, point: KnowledgePoint, goal_name: str, goal_description: str, target_role: str
    ) -> tuple[int, float]:
        """Score against a saved goal snapshot, never the global selector."""
        self._static_point(point)
        role = PROFILES.get(target_role, PROFILES["general_ai_pm"])
        topic_id = point.importance_topic or "Other"
        goal_text = f"{goal_name} {goal_description}".casefold()
        topic_profile = next((item for item in TOPIC_PROFILES if item.id == topic_id), TOPIC_PROFILES[-1])
        matched = any(keyword.casefold() in goal_text for keyword in topic_profile.keywords)
        base = GOAL_PROFILES.get(DEFAULT_GOAL)
        goal_relevance = 5 if matched else (base.topic_weights.get(topic_id, 3) if base else 3)
        role_relevance = role.importance_topic_weights.get(topic_id, 2)
        raw = (
            0.20 * max(0, point.base_importance_score)
            + 0.25 * goal_relevance
            + 0.25 * role_relevance
            + 0.15 * point.interview_value
            + 0.10 * max(0, point.practical_product_value)
            + 0.05 * max(0, point.prerequisite_importance)
        )
        return self._stars(round(max(0, min(5, raw)), 2)), float(goal_relevance)

    @staticmethod
    def goal_aware_unit_score(unit, point_stars: list[int], target_role: str) -> float:
        """Apply role-specific case/depth fit to cached point scores without model calls."""
        score = round(sum(point_stars) / len(point_stars), 1) if point_stars else 0.0
        role = PROFILES.get(target_role, PROFILES["general_ai_pm"])
        title = unit.title.casefold()
        if role.id == "ai_education_pm":
            education_terms = ("教育", "教学", "学习", "学生", "教师", "儿童", "育儿", "母婴", "亲子")
            if unit.unit_type == "PROJECT_CASE" and not any(term in title for term in education_terms):
                score = min(score, 3.0)
            if role.technical_depth_requirement == "P1" and any(
                term in title for term in ("lora", "mmdit", "sft训练数据集")
            ):
                score = min(score, 3.0)
        return score

    def _rate(self, repository: Repository, entity_type: str, entity, goal: str, role: str):
        raw, stars, label, reason = self.calculate_dynamic_importance(entity, goal, role)
        mastery, weakness_factor = self._mastery_and_weakness(
            repository, entity_type, entity
        )
        mastery_gap_factor = 0.5 + (100 - mastery) / 100
        priority = round(stars * mastery_gap_factor * weakness_factor, 3)
        return repository.upsert_importance_rating(
            entity_type=entity_type,
            entity_id=entity.id,
            learning_goal=goal,
            target_role=role,
            dynamic_score=stars,
            dynamic_raw=raw,
            priority_label=label,
            reason=reason,
            learning_priority=priority,
            mastery_snapshot=mastery,
        )

    def backfill(self, repository: Repository, *, recalculate: bool = True) -> dict:
        lessons = list(repository.db.scalars(select(Lesson).order_by(Lesson.id)).all())
        points = list(repository.db.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)).all())
        lesson_created = sum(self._static_lesson(item) for item in lessons)
        point_created = sum(self._static_point(item) for item in points)
        repository.db.flush()
        ratings = 0
        reused = 0
        if recalculate:
            goal = repository.get_learning_goal()
            role = repository.get_target_role()
            lesson_rating_ids = {
                item.entity_id
                for item in repository.importance_ratings("lesson", goal, role)
            }
            point_rating_ids = {
                item.entity_id
                for item in repository.importance_ratings("knowledge_point", goal, role)
            }
            for lesson in lessons:
                if lesson.id in lesson_rating_ids:
                    reused += 1
                else:
                    self._rate(repository, "lesson", lesson, goal, role)
                    ratings += 1
            for point in points:
                if point.id in point_rating_ids:
                    reused += 1
                else:
                    self._rate(repository, "knowledge_point", point, goal, role)
                    ratings += 1
        repository.db.commit()
        return {
            "lessons_total": len(lessons),
            "lessons_static_created": lesson_created,
            "knowledge_points_total": len(points),
            "knowledge_points_static_created": point_created,
            "ratings_updated": ratings,
            "ratings_reused": reused,
            "cache_hit": ratings == 0 and lesson_created == 0 and point_created == 0,
        }

    def recalculate(self, repository: Repository, learning_goal: str, target_role: str) -> dict:
        if learning_goal not in GOAL_PROFILES:
            raise ValueError("不支持的学习目标。")
        if target_role not in PROFILES:
            raise ValueError("不支持的目标岗位。")
        repository.set_learning_context(learning_goal, target_role)
        return self.backfill(repository, recalculate=True)

    def context(self, repository: Repository) -> dict:
        goal = GOAL_PROFILES.get(repository.get_learning_goal(), GOAL_PROFILES[DEFAULT_GOAL])
        role = PROFILES[repository.get_target_role()]
        return {
            "learning_goal": goal.id,
            "learning_goal_name": goal.name,
            "target_role": role.id,
            "target_role_name": role.name,
            "learning_goals": [{"id": item.id, "name": item.name} for item in GOAL_PROFILES.values()],
        }

    def recommendations(
        self, repository: Repository, course_id: int | None = None, minimum_stars: int = 0
    ) -> dict:
        cache = self.backfill(repository)
        context = self.context(repository)
        ratings = {
            item.entity_id: item
            for item in repository.importance_ratings(
                "lesson", context["learning_goal"], context["target_role"]
            )
        }
        statement = select(Lesson)
        if course_id is not None:
            statement = statement.where(Lesson.course_id == course_id)
        lessons = list(repository.db.scalars(statement.order_by(Lesson.id)).all())
        items = []
        for lesson in lessons:
            rating = ratings[lesson.id]
            if rating.dynamic_importance_score < minimum_stars:
                continue
            _, label_cn = LABELS[rating.dynamic_importance_score]
            items.append(
                {
                    "entity_type": "lesson",
                    "entity_id": lesson.id,
                    "page_id": lesson.id,
                    "course_id": lesson.course_id,
                    "page_title": lesson.title,
                    "chapter_title": lesson.chapter_title,
                    "section_title": lesson.section_title,
                    "source_url": lesson.url,
                    "knowledge_point_name": "",
                    "importance_topic": lesson.importance_topic,
                    "base_importance_score": lesson.base_importance_score,
                    "dynamic_importance_score": rating.dynamic_importance_score,
                    "dynamic_importance_raw": rating.dynamic_importance_raw,
                    "priority_label": rating.priority_label,
                    "priority_label_cn": label_cn,
                    "importance_reason": rating.importance_reason,
                    "learning_priority_score": rating.learning_priority_score,
                    "mastery_score": rating.mastery_snapshot,
                    "interview_value": lesson.interview_value,
                    "practical_product_value": lesson.practical_product_value,
                    "prerequisite_importance": lesson.prerequisite_importance,
                    "minimum_interview_path": rating.dynamic_importance_score == 5,
                }
            )
        items.sort(
            key=lambda item: (
                -item["learning_priority_score"],
                -item["interview_value"],
                -item["prerequisite_importance"],
                item["page_id"],
            )
        )
        return {**context, "total": len(items), "items": items, "cached": cache["cache_hit"]}

    def point_rating(self, repository: Repository, point: KnowledgePoint):
        self._static_point(point)
        goal, role = repository.get_learning_goal(), repository.get_target_role()
        rating = self._rate(repository, "knowledge_point", point, goal, role)
        repository.db.commit()
        return rating


importance_engine = ImportanceEngine()
