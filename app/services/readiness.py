import json
from pathlib import Path

from app.services.importance_engine import importance_engine
from app.services.target_roles import target_role_service

CONFIG = json.loads(
    (Path(__file__).parents[1] / "config" / "readiness.json").read_text(encoding="utf-8")
)
PAGE_IMPORTANCE_WEIGHTS = {int(key): value for key, value in CONFIG["page_weights"].items()}
COVERAGE_CAPS = tuple(tuple(item) for item in CONFIG["coverage_caps"])

CAPABILITY_MAPS = {
    "ai_education_pm": [
        {"id": "technical_understanding", "name": "AI技术基础", "weight": 20},
        {"id": "product_thinking", "name": "AI产品思维", "weight": 25},
        {"id": "application_and_delivery", "name": "AI应用落地", "weight": 20},
        {"id": "education_domain", "name": "AI+教育领域", "weight": 20},
        {"id": "interview_communication", "name": "面试与Case表达", "weight": 15},
    ]
}


def capability_map_for_role(role_id: str) -> list[dict]:
    return CAPABILITY_MAPS.get(
        role_id,
        [
            {"id": "technical_understanding", "name": "AI技术基础", "weight": 25},
            {"id": "product_thinking", "name": "产品思维", "weight": 25},
            {"id": "application_and_delivery", "name": "应用落地", "weight": 20},
            {"id": "business_judgment", "name": "业务判断", "weight": 15},
            {"id": "interview_communication", "name": "面试表达", "weight": 15},
        ],
    )


def apply_coverage_cap(score: int, coverage_percent: int) -> int:
    for threshold, cap in COVERAGE_CAPS:
        if coverage_percent < threshold:
            return min(score, cap)
    return score


def _point_evidence_strength(repository, point) -> float:
    evaluations = repository.attempts_with_evaluations(point.id)
    if not evaluations:
        return 0.0
    valid = [item for item in evaluations if item[0].interview_depth != "P3"]
    if not valid:
        return 0.0
    fingerprints = {
        item[0].question_fingerprint_json
        for item in valid
        if item[0].question_fingerprint_json not in ("", "{}", None)
    }
    reviews = repository.review_rows(point.id)
    review_days = {item.tested_at.date() for item in reviews}
    stages = {item[0].stage.casefold() for item in valid}
    if stages & {"case", "mock", "simulation", "interview"}:
        return 1.0
    if len(review_days) >= 2:
        return 0.8
    if len(fingerprints) >= 2 or len(valid) >= 2:
        return 0.6
    return 0.4


def _confidence(coverage_percent: int, strengths: list[float]) -> str:
    if coverage_percent < 20:
        return "LOW"
    if coverage_percent < 60:
        return "MEDIUM"
    return "HIGH" if any(strength >= 0.8 for strength in strengths) else "MEDIUM"


def _readiness_status(score: int) -> str:
    if score < 40:
        return "NOT_READY"
    if score < 60:
        return "EARLY_READY"
    if score < 75:
        return "INTERVIEW_READY"
    if score < 85:
        return "GOOD_READY"
    return "STRONG_READY"


def aggregate_page_scores(pages: list[dict]) -> dict:
    """Aggregate persisted page scores against the complete relevant page map."""
    included = [page for page in pages if page["importance"] in PAGE_IMPORTANCE_WEIGHTS]
    total_weight = sum(PAGE_IMPORTANCE_WEIGHTS[page["importance"]] for page in included)
    studied_weight = sum(
        PAGE_IMPORTANCE_WEIGHTS[page["importance"]]
        for page in included
        if page["has_evidence"]
    )
    if not total_weight:
        return {
            "course_mastery": 0,
            "interview_readiness": 0,
            "uncapped_interview_readiness": 0,
            "coverage_percent": 0,
            "studied_pages": 0,
            "eligible_pages": 0,
            "ignored_pages": len(pages),
        }
    interview_readiness = round(
        sum(
            page["interview_readiness"] * PAGE_IMPORTANCE_WEIGHTS[page["importance"]]
            for page in included
        )
        / total_weight
    )
    coverage_percent = round(studied_weight / total_weight * 100)
    return {
        "course_mastery": round(
            sum(
                page["course_mastery"] * PAGE_IMPORTANCE_WEIGHTS[page["importance"]]
                for page in included
            )
            / total_weight
        ),
        "interview_readiness": apply_coverage_cap(interview_readiness, coverage_percent),
        "uncapped_interview_readiness": interview_readiness,
        "coverage_percent": coverage_percent,
        "studied_pages": sum(page["has_evidence"] for page in included),
        "eligible_pages": len(included),
        "ignored_pages": len(pages) - len(included),
    }


class ReadinessService:
    def calculate(
        self,
        repository,
        target_role: str | None = None,
        course_id: int | None = None,
    ) -> dict:
        profile = target_role_service.get_profile(target_role or repository.get_target_role())
        # Recalculate lesson importance for the current goal/role. Page scores
        # themselves are read-only here and remain owned by the page algorithms.
        importance_engine.backfill(repository)
        ratings = {
            rating.entity_id: rating
            for rating in repository.importance_ratings(
                "lesson", repository.get_learning_goal(), repository.get_target_role()
            )
        }
        pages = []
        for lesson in repository.list_lesson_records(course_id):
            points = repository.list_knowledge_points(lesson.id)
            valid_points = [point for point in points if point.interview_depth != "P3"]
            strengths = [_point_evidence_strength(repository, point) for point in valid_points]
            evidence_strength = (
                sum(strengths) / len(strengths) if strengths else 0.0
            )
            page_readiness = target_role_service.page_readiness(
                repository, lesson.id, profile
            )
            pages.append(
                {
                    "lesson_id": lesson.id,
                    "title": lesson.title,
                    "importance": ratings[lesson.id].dynamic_importance_score,
                    "course_mastery": repository.page_mastery(lesson.id),
                    # A page score is evidence-weighted globally; its own score
                    # calculation remains untouched.
                    "interview_readiness": round(page_readiness * evidence_strength),
                    "evidence_strength": evidence_strength,
                    "point_count": len(valid_points),
                    "validated_point_count": sum(
                        strength > 0 for strength in strengths if strength is not None
                    ),
                    # Merely opening/extracting a page is not learning evidence.
                    "has_evidence": any(strength > 0 for strength in strengths),
                }
            )
        result = aggregate_page_scores(pages)
        strengths = [page["evidence_strength"] for page in pages if page["has_evidence"]]
        validated_points = sum(page["validated_point_count"] for page in pages)
        core_points = sum(page["point_count"] for page in pages)
        confidence = _confidence(result["coverage_percent"], strengths)
        capability_map = capability_map_for_role(profile.id)
        result.update(
            {
                "actual_global_interview_readiness": result["interview_readiness"],
                "readiness_status": _readiness_status(result["interview_readiness"]),
                "evidence_confidence": confidence,
                "core_coverage_percent": round(validated_points / core_points * 100)
                if core_points
                else 0,
                "capability_map": capability_map,
                "debug": {
                    "target_role": profile.id,
                    "capability_map": capability_map,
                    "dimension_weights": {
                        item["id"]: item["weight"] for item in capability_map
                    },
                    "total_core_weight": core_points,
                    "validated_weight": validated_points,
                    "coverage": result["coverage_percent"],
                    "confidence": confidence,
                    "page_contributions": pages,
                    "excluded_skippable_items": [
                        page for page in pages if page["importance"] not in PAGE_IMPORTANCE_WEIGHTS
                    ],
                    "estimated_score_isolated": None,
                    "final_actual_score": result["interview_readiness"],
                },
                "pages": pages,
            }
        )
        return result


readiness_service = ReadinessService()
