from app.db.models import MasteryScore
from app.db.repository import Repository

TRANSFER_TYPES = {"产品应用题", "技术选型题", "场景Case题", "面试题"}
QUESTION_TYPE_COUNT = 7


class MasteryCalculator:
    """Calculate mastery from persisted attempts; the LLM never supplies this value."""

    def update(self, repository: Repository, knowledge_point_id: int) -> MasteryScore:
        attempts = repository.attempts_with_scores(knowledge_point_id)
        evaluated_attempts = repository.attempts_with_evaluations(knowledge_point_id)
        reviews = repository.review_rows(knowledge_point_id)
        covered_types = {attempt.question_type for attempt, _ in attempts}
        coverage = round(min(100, len(covered_types) / QUESTION_TYPE_COUNT * 100))
        assessment = round(sum(score for _, score in attempts) / len(attempts)) if attempts else 0
        transfer_scores = [
            score for attempt, score in attempts if attempt.question_type in TRANSFER_TYPES
        ]
        transfer = round(sum(transfer_scores) / len(transfer_scores)) if transfer_scores else 0
        high_score_dates = {row.tested_at.date() for row in reviews if row.score >= 90}
        stability = 100 if len(high_score_dates) >= 2 else 50 if high_score_dates else 0
        mastery = round(0.40 * coverage + 0.35 * assessment + 0.15 * transfer + 0.10 * stability)
        latest_score = attempts[-1][1] if attempts else 0
        if len(high_score_dates) >= 2:
            status = "长期掌握"
        elif latest_score >= 90:
            status = "熟练"
        elif latest_score >= 85:
            status = "掌握较强"
        elif latest_score >= 70:
            status = "掌握良好"
        elif latest_score >= 60:
            status = "达到基础面试要求"
        elif attempts:
            status = "需要补强"
        else:
            status = "未学习"

        p1_scores = [
            evaluation.total_score
            for attempt, evaluation in evaluated_attempts
            if attempt.interview_depth == "P1"
        ]
        interview_scores = [
            evaluation.total_score
            for attempt, evaluation in evaluated_attempts
            if attempt.interview_depth != "P3"
        ]
        p1_core_score = p1_scores[-1] if p1_scores else 0
        recent_interview = interview_scores[-5:]
        interview_performance = (
            round(sum(recent_interview) / len(recent_interview))
            if recent_interview
            else 0
        )
        transfer_scores_for_ready = [
            evaluation.total_score
            for attempt, evaluation in evaluated_attempts
            if attempt.interview_depth != "P3" and attempt.question_type in TRANSFER_TYPES
        ]
        transfer_performance = max(transfer_scores_for_ready, default=0)
        latest_valid = next(
            (
                evaluation
                for attempt, evaluation in reversed(evaluated_attempts)
                if attempt.interview_depth != "P3"
            ),
            None,
        )
        no_serious_error = bool(latest_valid) and not latest_valid.critical_misconception
        interview_ready = bool(
            latest_valid and latest_valid.total_score >= 60 and no_serious_error
        )
        interview_status = "PASS" if interview_ready else "LEARNING" if latest_valid else "NOT_TESTED"
        conceptual_safety = 100 if no_serious_error else 0
        interview_readiness = round(
            0.45 * p1_core_score
            + 0.30 * interview_performance
            + 0.20 * transfer_performance
            + 0.05 * conceptual_safety
        )
        if interview_ready:
            interview_readiness = max(60, interview_readiness)
        return repository.upsert_mastery_score(
            knowledge_point_id,
            coverage,
            assessment,
            transfer,
            stability,
            mastery,
            status,
            p1_core_score,
            interview_readiness,
            interview_ready,
            interview_status,
        )


mastery_calculator = MasteryCalculator()
