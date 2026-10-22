"""Learning-unit capability labels and evidence-based dashboard aggregation."""

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgePoint, LearningGoal, LearningUnit, MasteryScore

CAPABILITIES = (
    ("foundation", "大模型基础"),
    ("rag", "RAG能力"),
    ("agent", "Agent能力"),
    ("evaluation", "AI评估能力"),
    ("product", "产品设计"),
    ("practice", "场景与项目实践"),
)

PATTERNS = {
    "foundation": r"foundation model|基础模型|大模型|语言模型|(?<![a-z])llm(?![a-z])|transformer|注意力|预训练|微调|sft|lora|prompt|提示词|few.shot",
    "rag": r"(?<![a-z])rag(?![a-z])|检索增强|知识库|向量检索|embedding",
    "agent": r"(?<![a-z])agent(?![a-z])|智能体|workflow|工作流|(?<![a-z])mcp(?![a-z])|多智能体|harness",
    "evaluation": r"评估|评测|测评|指标|benchmark|效果验证|验收|准确率|召回率",
    "product": r"产品设计|产品经理|产品思维|需求|竞品|原型|(?<![a-z])prd(?![a-z])|流程图|用户体验|产品目标",
    "practice": r"项目|案例|场景|落地|实施|交付|实操|教育|育儿|dify",
}


def capability_tags(title: str, source_names: list[str] | None = None) -> list[str]:
    """Tag a unit from its topic and named source points, never course body text."""
    text = " ".join([title, *(source_names or [])]).casefold()
    tags = [key for key, _name in CAPABILITIES if re.search(PATTERNS[key], text, re.IGNORECASE)]
    return tags or ["practice"]


def _ids(raw: str) -> list[int]:
    try:
        values = json.loads(raw or "[]")
        return [value for value in values if isinstance(value, int)] if isinstance(values, list) else []
    except (TypeError, ValueError):
        return []


def backfill_capability_tags(db: Session) -> int:
    """One-time local classification of older units; no model call or course rescan."""
    units = db.scalars(select(LearningUnit).where(LearningUnit.capability_tags_json == "[]")).all()
    point_ids = {pid for unit in units for pid in _ids(unit.source_knowledge_point_ids_json)}
    names = {point.id: point.name for point in db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))
    ).all()} if point_ids else {}
    for unit in units:
        unit.capability_tags_json = json.dumps(capability_tags(
            unit.title, [names[pid] for pid in _ids(unit.source_knowledge_point_ids_json) if pid in names]
        ), ensure_ascii=False)
    if units:
        db.commit()
    return len(units)


def capability_growth(db: Session, target_role: str) -> dict:
    """Compute growth from completed units and saved knowledge-point mastery."""
    units = db.scalars(
        select(LearningUnit).join(LearningGoal).where(
            LearningGoal.target_role == target_role, LearningGoal.status == "ACTIVE"
        )
    ).all()
    point_ids = {pid for unit in units for pid in _ids(unit.source_knowledge_point_ids_json)}
    scores = {row.knowledge_point_id: row.mastery_score for row in db.scalars(
        select(MasteryScore).where(MasteryScore.knowledge_point_id.in_(point_ids))
    ).all()} if point_ids else {}
    names = {point.id: point.name for point in db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))
    ).all()} if point_ids else {}
    totals = {key: 0 for key, _name in CAPABILITIES}
    earned = {key: 0.0 for key, _name in CAPABILITIES}
    completed_by_tag = {key: 0 for key, _name in CAPABILITIES}
    completed = 0
    total_credit = 0.0
    for unit in units:
        ids = _ids(unit.source_knowledge_point_ids_json)
        try:
            tags = json.loads(unit.capability_tags_json or "[]")
        except (TypeError, ValueError):
            tags = []
        valid_tags = [tag for tag in tags if tag in totals] if isinstance(tags, list) else []
        if not valid_tags:
            valid_tags = capability_tags(unit.title, [names[pid] for pid in ids if pid in names])
        credit = 0.0
        if unit.status == "COMPLETED":
            completed += 1
            point_scores = [scores[pid] for pid in ids if pid in scores]
            # Legacy completed units may have no point score; completion itself
            # is evidence of passing the existing mastery loop.
            credit = sum(point_scores) / len(point_scores) if point_scores else 60.0
            credit = max(0.0, min(100.0, credit))
        total_credit += credit
        for tag in valid_tags:
            totals[tag] += 1
            earned[tag] += credit
            if unit.status == "COMPLETED":
                completed_by_tag[tag] += 1
    return {
        "completed_units": completed,
        "total_units": len(units),
        "capability_overall": round(total_credit / len(units), 2) if units else 0,
        "capability_growth": [
            {"id": key, "name": name, "score": round(earned[key] / totals[key], 2) if totals[key] else 0,
             "completed": completed_by_tag[key], "total": totals[key]}
            for key, name in CAPABILITIES if totals[key]
        ],
    }
