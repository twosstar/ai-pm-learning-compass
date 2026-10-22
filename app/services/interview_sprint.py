import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.db.repository import Repository
from app.services.importance_engine import LABELS, importance_engine
from app.services.readiness import readiness_service
from app.services.target_roles import PROFILES, target_role_service

# China Standard Time is a fixed UTC+08:00 offset (no DST), so this remains
# deterministic even when system tzdata is unavailable.
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def today_local() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def calculate_current_day(sprint, today: date | None = None) -> int:
    if not sprint.start_date:
        return 1
    elapsed = max(0, ((today or today_local()) - sprint.start_date).days)
    return min(sprint.total_days, elapsed + 1)


class InterviewSprintService:
    @staticmethod
    def _time_budget(daily_minutes: int) -> dict[str, int]:
        extra = daily_minutes - 20
        remediation = 5 + extra * 25 // 100
        questions = 6 + extra * 35 // 100
        case = 5 + extra * 20 // 100
        review = daily_minutes - remediation - questions - case
        return {
            "remediation": remediation,
            "questions": questions,
            "case": case,
            "review": review,
        }

    @staticmethod
    def _ranked_candidates(repository: Repository, profile) -> tuple[list[dict], int]:
        candidates = []
        skipped_ready = 0
        for point in repository.list_all_knowledge_points():
            if point.interview_depth == "P3":
                continue
            readiness, ready = target_role_service.point_readiness(
                repository, point, profile
            )
            if ready:
                skipped_ready += 1
                continue
            rating = importance_engine.point_rating(repository, point)
            if repository.get_learning_goal() == "INTERVIEW_SPRINT" and rating.dynamic_importance_score < 3:
                continue
            weaknesses = repository.list_weaknesses(point.id)
            role_relevance = target_role_service.relevance(profile, point)
            frequency_score = round((point.interview_value + role_relevance) / 2)
            deferred = any(item.mistake_count >= 2 for item in weaknesses)
            deferred_bonus = 100 if deferred and rating.dynamic_importance_score >= 4 else 0
            priority = rating.learning_priority_score + deferred_bonus
            candidates.append(
                {
                    "point": point,
                    "readiness": readiness,
                    "weaknesses": weaknesses,
                    "role_relevance": role_relevance,
                    "frequency_score": frequency_score,
                    "importance_score": rating.dynamic_importance_score,
                    "priority": priority,
                    "deferred_review": deferred,
                }
            )
        candidates.sort(
            key=lambda item: (
                -item["priority"],
                -item["frequency_score"],
                item["readiness"],
                item["point"].id,
            )
        )
        return candidates, skipped_ready

    @staticmethod
    def _task(
        *,
        point,
        day: int,
        task_type: str,
        title: str,
        rationale: str,
        minutes: int,
        rank: int,
        question_count: int = 0,
        expected_gain: int = 0,
    ) -> dict:
        if task_type in {"关键知识补强", "KNOWLEDGE_REMEDIATION"}:
            target_type, module, action, mode = "knowledge_point", "learning", "开始补强", "remediation"
        elif task_type in {"高价值面试题", "HIGH_VALUE_INTERVIEW_QUESTION"}:
            target_type, module, action, mode = "knowledge_point", "interview", "开始答题", "interview"
        elif task_type in {"弱点复习", "WEAKNESS_REVIEW"}:
            target_type, module, action, mode = "knowledge_point", "learning", "开始复习", "review"
        else:
            target_type, module, action, mode = "knowledge_point", "interview", "开始Case", "case"
        return {
            "knowledge_point_id": point.id if point else None,
            "day_number": day,
            "task_type": task_type,
            "target_type": target_type,
            "target_id": str(point.id) if point else None,
            "target_title": point.name if point else title,
            "target_module": module,
            "action_label": action,
            "deep_link": f"/{module}?page_id={point.lesson_id if point else ''}&knowledge_point_id={point.id if point else ''}&mode={mode}",
            "title": title,
            "rationale": rationale,
            "estimated_minutes": minutes,
            "question_count": question_count,
            "expected_gain": expected_gain,
            "priority_rank": rank,
        }

    def create(
        self,
        repository: Repository,
        *,
        preparation_days: int,
        daily_minutes: int,
        target_role: str,
        learning_goal: str | None = None,
        target_interview_readiness: int = 60,
        replan: bool = False,
    ) -> dict:
        if target_role not in PROFILES:
            raise ValueError("不支持的目标岗位。")
        requested_goal = learning_goal or repository.get_learning_goal()
        existing = repository.get_active_interview_sprint(target_role, requested_goal)
        if existing and not replan:
            return self.view(repository, existing)
        if existing and replan:
            # Replanning is intentionally idempotent in this P0 fix: preserve
            # the sprint identity/start date and return its persisted task set.
            return self.view(repository, existing)
        importance_engine.recalculate(
            repository, learning_goal or repository.get_learning_goal(), target_role
        )
        profile = PROFILES[target_role]
        all_points = repository.list_all_knowledge_points()
        if not all_points:
            raise ValueError("知识库中还没有知识点，请先采集课程并生成学习任务。")
        candidates, skipped_ready = self._ranked_candidates(repository, profile)
        # The sprint baseline must use the same authoritative global readiness
        # calculation as the dashboard, explicitly for the requested role.
        # Using the priority dashboard's implicit selected role could persist a
        # stale/different baseline (for example 5) while the homepage shows 0.
        baseline = readiness_service.calculate(
            repository, target_role=profile.id
        )["interview_readiness"]
        target_interview_readiness = max(40, min(100, target_interview_readiness))
        score_gap = max(0, target_interview_readiness - baseline)
        estimated_required_minutes = score_gap * 30
        highest_risks = [item["point"].name for item in candidates[:3]]
        budget = self._time_budget(daily_minutes)
        tasks: list[dict] = []
        projected = baseline
        if candidates:
            for day in range(1, preparation_days + 1):
                if projected >= target_interview_readiness:
                    break
                primary = candidates[(day - 1) % len(candidates)]
                question_topics = [
                    candidates[(day - 1 + offset) % len(candidates)]
                    for offset in range(min(5, max(2, budget["questions"] // 8)))
                ]
                case_target = max(
                    question_topics,
                    key=lambda item: (
                        item["role_relevance"], item["point"].interview_value
                    ),
                )
                weak_candidates = [item for item in candidates if item["weaknesses"]]
                review_target = (
                    weak_candidates[(day - 1) % len(weak_candidates)]
                    if weak_candidates
                    else primary
                )
                day_gain = min(target_interview_readiness - projected, max(1, round(daily_minutes / 30)))
                weakness_text = (
                    "、".join(item.weakness_type for item in primary["weaknesses"][:2])
                    or "P1/P2核心理解尚未达到当前岗位要求"
                )
                point = primary["point"]
                tasks.extend(
                    [
                        self._task(
                            point=point,
                            day=day,
                            task_type="关键知识补强",
                            title=f"补强：{point.name}",
                            rationale=f"{LABELS[primary['importance_score']][1]} · 当前{primary['readiness']}分；{weakness_text}。",
                            minutes=budget["remediation"],
                            rank=1,
                            expected_gain=day_gain,
                        ),
                        self._task(
                            point=point,
                            day=day,
                            task_type="高价值面试题",
                            title="高价值问题："
                            + "、".join(item["point"].name for item in question_topics),
                            rationale=(
                                f"完成{len(question_topics)}道{LABELS[question_topics[0]['importance_score']][1]}高频题，优先检验为什么、"
                                "选型和Trade-off。"
                            ),
                            minutes=budget["questions"],
                            rank=2,
                            question_count=len(question_topics),
                        ),
                        self._task(
                            point=case_target["point"],
                            day=day,
                            task_type="产品Case / 技术选型",
                            title=f"Case：{case_target['point'].name}",
                            rationale=f"围绕{profile.case_focus[(day - 1) % len(profile.case_focus)]}完成结构化回答。",
                            minutes=budget["case"],
                            rank=3,
                            question_count=1,
                        ),
                        self._task(
                            point=review_target["point"],
                            day=day,
                            task_type="弱点复习",
                            title=f"复习：{review_target['point'].name}",
                            rationale="复述上次遗漏，检查严重概念错误是否已经消除。",
                            minutes=budget["review"],
                            rank=4,
                        ),
                    ]
                )
                projected += day_gain
        sprint = repository.create_interview_sprint(
            target_role=profile.id,
            learning_goal=repository.get_learning_goal(),
            preparation_days=preparation_days,
            daily_minutes=daily_minutes,
            baseline_readiness=baseline,
            projected_readiness=projected,
            target_interview_readiness=target_interview_readiness,
            estimated_required_minutes=estimated_required_minutes,
            highest_risks=highest_risks,
            skipped_ready_count=skipped_ready,
            tasks=tasks,
            start_date=today_local(),
        )
        return self.view(repository, sprint)

    def view(self, repository: Repository, sprint) -> dict:
        if not sprint.start_date:
            # Historical rows created before start_date was persisted are
            # repaired once from their creation date, then treated normally.
            sprint.start_date = (
                sprint.created_at.astimezone(LOCAL_TIMEZONE).date()
                if sprint.created_at
                else today_local()
            )
        sprint.current_day = calculate_current_day(sprint)
        repository.db.commit()
        profile = target_role_service.get_profile(sprint.target_role)
        tasks_by_day = defaultdict(list)
        for task in repository.list_interview_sprint_tasks(sprint.id):
            tasks_by_day[task.day_number].append(task)
        # Sprint never owns an actual score; read the single global calculation.
        actual_readiness = readiness_service.calculate(
            repository, target_role=sprint.target_role
        )["interview_readiness"]
        # Planned day ranges are forecasts.  Anchor them to the live global
        # score so TODAY never displays a number that disagrees with the
        # homepage's actual readiness.
        current_score = actual_readiness
        score_gap = max(0, sprint.target_interview_readiness - actual_readiness)
        days = []
        for day_number in range(1, sprint.preparation_days + 1):
            day_tasks = tasks_by_day[day_number]
            gain = sum(task.expected_gain for task in day_tasks)
            after = min(100, current_score + gain)
            days.append(
                {
                    "day_number": day_number,
                    "total_minutes": sum(task.estimated_minutes for task in day_tasks),
                    "readiness_before": current_score,
                    "readiness_after": after,
                    "tasks": [
                        {
                            "id": task.id,
                            "day_number": task.day_number,
                            "task_type": task.task_type,
                            "knowledge_point_id": task.knowledge_point_id,
                            "title": task.title,
                            "rationale": task.rationale,
                            "estimated_minutes": task.estimated_minutes,
                            "question_count": task.question_count,
                            "expected_gain": task.expected_gain,
                            "status": task.status,
                            "target_type": task.target_type,
                            "target_id": task.target_id,
                            "target_title": task.target_title or task.title,
                            "target_module": task.target_module,
                            "action_label": task.action_label,
                            "deep_link": task.deep_link,
                        }
                        for task in day_tasks
                    ],
                }
            )
            current_score = after
        return {
            "id": sprint.id,
            "target_role": sprint.target_role,
            "target_role_name": profile.name,
            "status": sprint.status.upper(),
            "learning_goal": sprint.learning_goal,
            "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
            "total_days": sprint.total_days,
            "current_day": sprint.current_day,
            "remaining_days": max(0, sprint.total_days - sprint.current_day + 1),
            "current_score": actual_readiness,
            "target_score": sprint.target_score or sprint.target_interview_readiness,
            "actual_global_interview_readiness": actual_readiness,
            "sprint_start_readiness": sprint.baseline_readiness,
            "estimated_end_readiness": min(
                sprint.target_interview_readiness,
                actual_readiness
                + max(0, sprint.projected_readiness - sprint.baseline_readiness),
            ),
            "planned_gain": max(0, sprint.projected_readiness - sprint.baseline_readiness),
            "sprint_phase": (
                "INTERVIEW_CONSOLIDATION" if actual_readiness >= 60 else "FOUNDATION_SPRINT"
            ),
            "needs_replan": repository.get_target_role() != sprint.target_role,
            "preparation_days": sprint.preparation_days,
            "daily_minutes": sprint.daily_minutes,
            "baseline_readiness": sprint.baseline_readiness,
            "projected_readiness": sprint.projected_readiness,
            "target_interview_readiness": sprint.target_interview_readiness,
            "score_gap": score_gap,
            "estimated_required_minutes": score_gap * 30,
            "highest_risks": json.loads(sprint.highest_risks_json or "[]"),
            "skipped_interview_ready": sprint.skipped_ready_count,
            "days": days,
        }

    def active(self, repository: Repository) -> dict | None:
        sprint = repository.get_active_interview_sprint()
        return self.view(repository, sprint) if sprint else None


interview_sprint_service = InterviewSprintService()
