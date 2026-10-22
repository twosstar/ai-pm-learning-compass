"""Deterministic daily tasks derived from the selected role's saved learning path."""

import json
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LearningGoal, LearningSession, LearningUnit

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DAILY_TASK_LIMIT = 3


def _json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _local_date(value: datetime | None):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI).date()


def _status_label(status: str) -> str:
    return {
        "NOT_STARTED": "未开始",
        "IN_PROGRESS": "学习中",
        "COMPLETED": "已完成",
    }.get(status, "未开始")


def _reason(goal: LearningGoal, unit: LearningUnit, completed_today: bool) -> str:
    if completed_today:
        return f"今日已完成，掌握度 {unit.mastery}% 已记录；可复习巩固。"
    if unit.status == "IN_PROGRESS":
        return "你已开始这个单元；继续完成后会计入当前学习目标的进度。"
    if unit.status == "COMPLETED":
        return "该单元已完成；今日待学内容不足时，安排复习以巩固岗位能力。"
    capabilities = [str(tag).strip() for tag in _json_list(unit.capability_tags_json) if str(tag).strip()]
    capability_text = f"，重点覆盖：{'、'.join(capabilities[:3])}" if capabilities else ""
    if unit.importance >= 4:
        return (
            f"来自「{goal.name}」学习路径的核心单元（重要度 {unit.importance}/5），"
            f"按路径顺序推进可优先补齐目标能力{capability_text}。"
        )
    return f"来自「{goal.name}」的已保存学习路径，按编排顺序逐步补齐目标岗位能力{capability_text}。"


def daily_learning_plan(db: Session, target_role: str, target_role_name: str) -> dict:
    """Build a stable, API-free daily plan from the latest active path for this role."""
    goal = db.scalar(
        select(LearningGoal)
        .where(LearningGoal.target_role == target_role, LearningGoal.status == "ACTIVE")
        .order_by(LearningGoal.updated_at.desc(), LearningGoal.id.desc())
        .limit(1)
    )
    if goal is None:
        return {
            "goal_id": None,
            "goal_name": "",
            "target_role_name": target_role_name,
            "daily_target": 0,
            "completed_today": 0,
            "estimated_minutes": 0,
            "remaining_minutes": 0,
            "tasks": [],
        }

    units = list(
        db.scalars(
            select(LearningUnit)
            .where(LearningUnit.goal_id == goal.id)
            .order_by(LearningUnit.order_index, LearningUnit.id)
        ).all()
    )
    daily_target = min(DAILY_TASK_LIMIT, len(units))
    if not units:
        return {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "target_role_name": target_role_name,
            "daily_target": 0,
            "completed_today": 0,
            "estimated_minutes": 0,
            "remaining_minutes": 0,
            "tasks": [],
        }

    unit_ids = [unit.id for unit in units]
    sessions = db.scalars(
        select(LearningSession).where(
            LearningSession.learning_unit_id.in_(unit_ids), LearningSession.completed.is_(True)
        )
    ).all()
    today = datetime.now(SHANGHAI).date()
    completed_at: dict[int, datetime] = {}
    for session in sessions:
        if _local_date(session.updated_at or session.created_at) == today and session.learning_unit_id:
            previous = completed_at.get(session.learning_unit_id)
            stamp = session.updated_at or session.created_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if previous is None or stamp > previous:
                completed_at[session.learning_unit_id] = stamp

    completed_today_units = [unit for unit in units if unit.id in completed_at]
    completed_today_units.sort(key=lambda unit: (completed_at[unit.id], unit.order_index), reverse=True)
    in_progress = [unit for unit in units if unit.status == "IN_PROGRESS"]
    not_started = [unit for unit in units if unit.status == "NOT_STARTED"]
    previously_completed = [unit for unit in units if unit.status == "COMPLETED" and unit.id not in completed_at]

    selected: list[LearningUnit] = []
    seen: set[int] = set()
    for group in (completed_today_units, in_progress, not_started, previously_completed):
        for unit in group:
            if unit.id not in seen:
                selected.append(unit)
                seen.add(unit.id)
                if len(selected) == daily_target:
                    break
        if len(selected) == daily_target:
            break

    tasks = []
    for unit in selected:
        is_completed_today = unit.id in completed_at
        tasks.append(
            {
                "id": unit.id,
                "title": unit.title,
                "status": unit.status,
                "status_label": _status_label(unit.status),
                "importance": unit.importance,
                "importance_label": "核心" if unit.importance >= 4 else "重点" if unit.importance == 3 else "补充",
                "estimated_minutes": max(1, int(unit.estimated_minutes or 15)),
                "mastery": int(unit.mastery or 0),
                "capability_tags": _json_list(unit.capability_tags_json),
                "completed_today": is_completed_today,
                "why_recommended": _reason(goal, unit, is_completed_today),
            }
        )

    return {
        "goal_id": goal.id,
        "goal_name": goal.name,
        "target_role_name": target_role_name,
        "daily_target": daily_target,
        "completed_today": min(daily_target, sum(1 for task in tasks if task["completed_today"])),
        "estimated_minutes": sum(task["estimated_minutes"] for task in tasks),
        "remaining_minutes": sum(task["estimated_minutes"] for task in tasks if not task["completed_today"]),
        "tasks": tasks,
    }
