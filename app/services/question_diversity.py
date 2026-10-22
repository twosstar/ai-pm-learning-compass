import json
import re

from app.schemas.learning import GeneratedQuestion, QuestionFingerprint


def _terms(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", value.casefold()).strip()
    words = {item for item in normalized.split() if len(item) > 1}
    chinese = "".join(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    words.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return words


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class QuestionDiversityService:
    """Fingerprint-based semantic guard for the five most recent related questions."""

    @staticmethod
    def ensure_fingerprint(question: GeneratedQuestion, point_name: str) -> GeneratedQuestion:
        fingerprint = question.question_fingerprint
        fingerprint.knowledge_point = fingerprint.knowledge_point or point_name
        fingerprint.question_type = fingerprint.question_type or question.question_type
        fingerprint.tested_skill = fingerprint.tested_skill or "technical_reasoning"
        fingerprint.scenario = fingerprint.scenario or "concept_explanation"
        fingerprint.reasoning_target = (
            fingerprint.reasoning_target
            or " / ".join(question.assessment_focus[:2])
            or "explain_core_mechanism"
        )
        fingerprint.expected_answer_dimensions = (
            fingerprint.expected_answer_dimensions
            or question.must_have_points
            or question.assessment_focus
        )[:8]
        return question

    @staticmethod
    def attempt_fingerprint(attempt) -> QuestionFingerprint:
        try:
            raw = json.loads(attempt.question_fingerprint_json or "{}")
            fingerprint = QuestionFingerprint.model_validate(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            fingerprint = QuestionFingerprint()
        if not fingerprint.question_type:
            fingerprint.question_type = attempt.question_type
        if not fingerprint.reasoning_target:
            try:
                focus = json.loads(attempt.assessment_focus_json or "[]")
            except (TypeError, json.JSONDecodeError):
                focus = []
            fingerprint.reasoning_target = " / ".join(focus[:2]) or attempt.question
        return fingerprint

    def similarity(self, candidate: GeneratedQuestion, attempt) -> float:
        left = candidate.question_fingerprint
        right = self.attempt_fingerprint(attempt)
        score = 0.0
        if left.reasoning_target.casefold() == right.reasoning_target.casefold():
            score += 0.35
        else:
            score += 0.35 * _jaccard(_terms(left.reasoning_target), _terms(right.reasoning_target))
        if left.tested_skill.casefold() == right.tested_skill.casefold():
            score += 0.20
        if left.scenario.casefold() == right.scenario.casefold():
            score += 0.15
        score += 0.15 * _jaccard(
            _terms(" ".join(left.expected_answer_dimensions)),
            _terms(" ".join(right.expected_answer_dimensions)),
        )
        score += 0.15 * _jaccard(_terms(candidate.question), _terms(attempt.question))
        return round(score, 3)

    def conflicts(self, candidate: GeneratedQuestion, recent_attempts: list) -> bool:
        return any(self.similarity(candidate, attempt) >= 0.70 for attempt in recent_attempts[-5:])

    @staticmethod
    def targeted_angle(failure_count: int, result) -> dict[str, str]:
        missing = (
            result.weak_concepts
            or result.weak_reasoning
            or result.weak_product_application
            or result.missing_points
            or result.incorrect_points
        )
        target = "、".join(missing[:3]) or "当前遗漏的核心机制"
        if failure_count <= 1:
            return {
                "question_type": "基础定义题",
                "tested_skill": "focused_concept_check",
                "scenario": "concrete_example_judgement",
                "reasoning_target": target,
                "instruction": "换成一个具体例子或局部判断，只验证遗漏概念，不得要求重述原答案。",
            }
        return {
            "question_type": "场景Case题",
            "tested_skill": "scenario_application",
            "scenario": "train_test_or_business_signal_diagnosis",
            "reasoning_target": target,
            "instruction": "换成场景判断题，让用户从数据或业务现象识别问题并解释因果关系。",
        }


question_diversity_service = QuestionDiversityService()
