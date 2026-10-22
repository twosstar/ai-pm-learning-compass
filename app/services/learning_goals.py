import asyncio
import json
import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerEvaluation,
    Concept,
    ConceptRelation,
    Course,
    GoalSource,
    KnowledgePoint,
    LearningGoal,
    LearningGoalCompileReport,
    LearningSession,
    LearningUnit,
    Lesson,
    MasteryScore,
    QuestionAttempt,
)
from app.services.capability_growth import capability_tags
from app.services.importance_engine import importance_engine
from app.services.learning_goal_compiler import (
    BucketCompileOutput,
    compile_learning_candidates,
    infer_learning_unit_type,
    learning_phase,
    normalize_learning_topic_title,
    topological_learning_order,
)
from app.services.llm import llm_service


class UnitPlan(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    knowledge_point_ids: list[int] = Field(min_length=1)
    unit_type: Literal["MERGED_UNIT", "STANDALONE_UNIT"] = "MERGED_UNIT"
    merge_type: Literal["EXACT_DUPLICATE", "COMPLEMENTARY", "DEPTH_LAYERED", "NONE"] = "COMPLEMENTARY"
    prerequisite_indices: list[int] = Field(default_factory=list)


class UnitPlanOutput(BaseModel):
    units: list[UnitPlan]


def _json(value):
    try:
        return json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []


def _normalize(value: str) -> str:
    title = re.sub(r"^\s*(?:第)?\d+(?:[.-]\d+)*[、.．:：\-]?\s+", "", value or "")
    return re.sub(r"[\W_]+", "", title.casefold(), flags=re.UNICODE)


def _course_map(db: Session):
    return {course.id: course for course in db.scalars(select(Course)).all()}


def _candidate_payload(db: Session):
    rows = db.execute(
        select(KnowledgePoint, Lesson, Course)
        .join(Lesson, Lesson.id == KnowledgePoint.lesson_id)
        .join(Course, Course.id == Lesson.course_id)
        .where(KnowledgePoint.category != "Section")
        .order_by(Course.id, Lesson.id, KnowledgePoint.id)
    ).all()
    return [
        {
            "knowledge_point_id": point.id,
            "knowledge_point": point.name,
            "description": (point.description or "")[:500],
            "category": point.category,
            "prerequisite": (point.prerequisite or "")[:200],
            "course_id": course.id,
            "course_name": course.name,
            "lesson_id": lesson.id,
            "lesson_title": lesson.title,
            "chapter_title": lesson.chapter_title,
            "section_title": lesson.section_title,
        }
        for point, lesson, course in rows
    ]


async def recommend(db: Session, name: str, description: str, target_role: str) -> dict:
    candidates = _candidate_payload(db)
    if not candidates:
        return {"items": []}
    class ScoredItem(BaseModel):
        knowledge_point_id: int
        relevance_score: int = Field(ge=0, le=100)
        recommendation: Literal["INCLUDE", "PARTIAL", "EXCLUDE"] = "INCLUDE"
        reason: str = ""
    class ScoredOutput(BaseModel):
        items: list[ScoredItem]

    def tokens(value: str) -> set[str]:
        result = set(re.findall(r"[a-z0-9]+", value.casefold()))
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", value):
            result.add(phrase)
            for size in (2, 3, 4):
                result.update(phrase[index:index + size] for index in range(len(phrase) - size + 1))
        return result

    terms = tokens(f"{name} {description} {target_role}")
    def fallback(batch):
        items = []
        for item in batch:
            text = " ".join(str(item[key]) for key in ("knowledge_point", "description", "category", "lesson_title", "chapter_title", "section_title"))
            matched = terms.intersection(tokens(text))
            score = min(95, len(matched) * 25)
            items.append(ScoredItem(knowledge_point_id=item["knowledge_point_id"], relevance_score=score,
                recommendation="INCLUDE" if score >= 50 else "PARTIAL" if score >= 25 else "EXCLUDE",
                reason="与目标关键词匹配：" + "、".join(sorted(matched)) if matched else "课程知识点与目标关键词关联较弱。"))
        return ScoredOutput(items=items)

    system = "你是课程筛选助手。依据学习目标、岗位，逐个评估输入知识点以及所属章节。仅给出与目标直接相关的知识点高分 INCLUDE、部分相关 PARTIAL、暂不推荐 EXCLUDE。不能按整门课程笼统判断；评价理由要具体。不可创造输入之外的知识点 ID。"
    scored = {}
    fallback_batches = 0
    # A large library can take minutes when every DeepSeek batch runs serially.
    # Bound both batch size and concurrent requests; one slow call must not hold
    # the whole course list indefinitely.
    semaphore = asyncio.Semaphore(4)

    async def score_batch(batch):
        used_fallback = False

        def safe_fallback():
            nonlocal used_fallback
            used_fallback = True
            return fallback(batch)

        async with semaphore:
            try:
                output = await asyncio.wait_for(
                    llm_service.complete_structured(
                        ScoredOutput,
                        system,
                        json.dumps({"goal": name, "description": description, "target_role": target_role, "candidates": batch}, ensure_ascii=False),
                        fallback=safe_fallback,
                        retries=0,
                        max_tokens=3000,
                    ),
                    timeout=45,
                )
            except TimeoutError:
                output = safe_fallback()
        return output, used_fallback

    batches = [candidates[offset:offset + 25] for offset in range(0, len(candidates), 25)]
    for output, used_fallback in await asyncio.gather(*(score_batch(batch) for batch in batches)):
        fallback_batches += int(used_fallback)
        scored.update({item.knowledge_point_id: item for item in output.items})
    grouped = defaultdict(list)
    for candidate in candidates:
        score = scored.get(candidate["knowledge_point_id"]) or ScoredItem(
            knowledge_point_id=candidate["knowledge_point_id"], relevance_score=0,
            recommendation="EXCLUDE", reason="AI 未返回该知识点的推荐判断。",
        )
        grouped[candidate["lesson_id"]].append((candidate, score))
    items = []
    for selected in grouped.values():
        candidate = selected[0][0]
        scores = [row[1] for row in selected]
        average = round(sum(row.relevance_score for row in scores) / len(scores))
        labels = {row.recommendation for row in scores}
        recommendation = "INCLUDE" if "INCLUDE" in labels else "PARTIAL" if "PARTIAL" in labels else "EXCLUDE"
        items.append({"course_id": candidate["course_id"], "course_name": candidate["course_name"],
            "lesson_id": candidate["lesson_id"], "lesson_title": candidate["lesson_title"],
            "chapter_title": candidate["chapter_title"], "section_title": candidate["section_title"],
            "knowledge_point_ids": [row[0]["knowledge_point_id"] for row in selected if row[1].recommendation != "EXCLUDE"],
            "knowledge_point_names": [row[0]["knowledge_point"] for row in selected if row[1].recommendation != "EXCLUDE"],
            "relevance_score": average, "recommendation": recommendation,
            "reason": "；".join(dict.fromkeys(row.reason for row in scores if row.reason))})
    source = "AI" if not fallback_batches else "KEYWORD_FALLBACK" if fallback_batches == len(batches) else "MIXED"
    return {"items": sorted(items, key=lambda item: (-item["relevance_score"], item["course_name"], item["lesson_title"])), "analysis_source": source}


def _validate_sources(db: Session, sources: list[dict]) -> list[dict]:
    valid = []
    for source in sources:
        course = db.get(Course, source["course_id"])
        if not course:
            raise ValueError(f"课程 {source['course_id']} 不存在。")
        lessons = {lesson.id: lesson for lesson in db.scalars(select(Lesson).where(Lesson.course_id == course.id)).all()}
        lesson_ids = set(source.get("lesson_ids", []))
        point_ids = set(source.get("knowledge_point_ids", []))
        if lesson_ids - lessons.keys():
            raise ValueError("选择的章节不属于对应课程。")
        points = db.scalars(select(KnowledgePoint).join(Lesson).where(
            Lesson.course_id == course.id, KnowledgePoint.category != "Section"
        )).all()
        point_map = {point.id: point for point in points}
        if point_ids - point_map.keys():
            raise ValueError("选择的知识点不属于对应课程。")
        if not lesson_ids and point_ids:
            lesson_ids = {point_map[point_id].lesson_id for point_id in point_ids}
        if not point_ids:
            point_ids = {point.id for point in points if not lesson_ids or point.lesson_id in lesson_ids}
        if lesson_ids:
            point_ids = {point_id for point_id in point_ids if point_map[point_id].lesson_id in lesson_ids}
        valid.append({**source, "lesson_ids": sorted(lesson_ids), "knowledge_point_ids": sorted(point_ids)})
    return valid


def _fallback_plan(points: list[KnowledgePoint]) -> UnitPlanOutput:
    groups = defaultdict(list)
    for point in points:
        groups[_normalize(point.name) or str(point.id)].append(point)
    units = []
    for group in groups.values():
        units.append(UnitPlan(title=group[0].name, knowledge_point_ids=[p.id for p in group],
            unit_type="MERGED_UNIT" if len(group) > 1 else "STANDALONE_UNIT",
            merge_type="EXACT_DUPLICATE" if len(group) > 1 else "NONE"))
    return UnitPlanOutput(units=units)


def _merge_exact_duplicate_units(
    units: list[UnitPlan], points: list[KnowledgePoint]
) -> list[UnitPlan]:
    """Guarantee that identical point names from different sources share one unit."""
    points_by_id = {point.id: point for point in points}
    names = defaultdict(list)
    for point in points:
        names[_normalize(point.name) or str(point.id)].append(point.id)
    result = list(units)
    redirected = {}
    point_order = {point.id: index for index, point in enumerate(points)}

    for duplicate_ids in names.values():
        if len(duplicate_ids) < 2:
            continue
        duplicate_set = set(duplicate_ids)
        containing = [
            index for index, unit in enumerate(result)
            if unit and duplicate_set.intersection(unit.knowledge_point_ids)
        ]
        if not containing:
            continue
        primary_index = containing[0]
        primary = result[primary_index]
        if primary is None:
            continue
        primary_ids = set(primary.knowledge_point_ids)
        merged_ids = sorted(primary_ids | duplicate_set, key=lambda item: point_order.get(item, 10**9))
        for index in containing[1:]:
            unit = result[index]
            if unit is None:
                continue
            remaining = [item for item in unit.knowledge_point_ids if item not in duplicate_set]
            if remaining:
                result[index] = unit.model_copy(update={"knowledge_point_ids": remaining})
            else:
                result[index] = None
                redirected[index] = primary_index
        exact_only = set(merged_ids) == duplicate_set
        result[primary_index] = primary.model_copy(update={
            "title": points_by_id[duplicate_ids[0]].name if exact_only else primary.title,
            "knowledge_point_ids": merged_ids,
            "unit_type": "MERGED_UNIT",
            "merge_type": "EXACT_DUPLICATE" if exact_only else primary.merge_type,
        })

    kept = [(index, unit) for index, unit in enumerate(result) if unit]
    old_to_new = {old: new for new, (old, _) in enumerate(kept)}
    for old, primary in redirected.items():
        while primary in redirected:
            primary = redirected[primary]
        if primary in old_to_new:
            old_to_new[old] = old_to_new[primary]
    cleaned = []
    for old_index, unit in kept:
        prerequisites = []
        for index in unit.prerequisite_indices:
            mapped = old_to_new.get(index)
            if mapped is not None and mapped != old_to_new[old_index] and mapped not in prerequisites:
                prerequisites.append(mapped)
        cleaned.append(unit.model_copy(update={"prerequisite_indices": prerequisites}))
    return cleaned


async def _build_units(
    db: Session, goal: LearningGoal, sources: list[dict], *, compile_mode: str = "FULL"
) -> list[LearningUnit]:
    point_ids = list(dict.fromkeys(point_id for source in sources for point_id in source["knowledge_point_ids"]))
    points = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))).all()) if point_ids else []
    lessons = {lesson.id: lesson for lesson in db.scalars(select(Lesson).where(Lesson.id.in_({p.lesson_id for p in points}))).all()} if points else {}
    courses = _course_map(db)
    items = []
    for point in points:
        lesson = lessons.get(point.lesson_id)
        course = courses.get(lesson.course_id) if lesson else None
        if not lesson or not course:
            continue
        try:
            evidence = json.loads(point.source_evidence_json or "[]")
            evidence_text = " ".join(str(item.get("text", "")) for item in evidence if isinstance(item, dict))
        except (TypeError, json.JSONDecodeError):
            evidence_text = ""
        items.append({
            "id": point.id, "name": point.name, "description": point.description or "",
            "category": point.category or "", "difficulty": point.difficulty or "基础",
            "prerequisite": point.prerequisite or "", "course_name": course.name,
            "lesson_title": lesson.title, "section_title": lesson.section_title or lesson.chapter_title or "",
            "source_evidence": evidence_text or point.description or point.level_1 or "",
            "source_quality": min(1.0, max(0.0, (point.transfer_score or 0) / 100)),
        })

    plans, compile_stats = await compile_learning_candidates(
        items, goal_name=goal.name, goal_description=goal.description,
        target_role=goal.target_role, llm_service=llm_service,
    )
    for plan in plans:
        source_points = [point for point in points if point.id in plan["source_knowledge_point_ids"]]
        stars = [importance_engine.goal_aware_point_importance(
            point, goal.name, goal.description, goal.target_role
        )[0] for point in source_points]
        plan["importance"] = max(stars, default=0)
        plan["goal_relevance"] = sum(stars) / max(1, len(stars))
        difficulty = {"基础": 1, "初级": 1, "中级": 2, "进阶": 3, "高级": 3, "专家": 4}
        plan["difficulty"] = max((difficulty.get(point.difficulty, 2) for point in source_points), default=1)
        plan["source_quality"] = max((float(item["source_quality"]) for item in items if item["id"] in plan["source_knowledge_point_ids"]), default=0)
        plan["mastery"] = 0
        plan["prerequisite_names"] = [
            req.strip() for point in source_points for req in re.split(r"[,，、;；\n]", point.prerequisite or "") if req.strip()
        ]

    point_prerequisites = {point.id: [part.strip() for part in re.split(r"[,，、;；\n]", point.prerequisite or "") if part.strip()] for point in points}
    concept_rows = db.scalars(select(Concept)).all()
    concept_point_ids = {row.id: set(_json(row.source_kp_ids_json)) & set(point_ids) for row in concept_rows}
    point_concepts = {point_id: concept_id for concept_id, ids in concept_point_ids.items() for point_id in ids}
    concept_edges = []
    if point_concepts:
        for relation in db.scalars(select(ConceptRelation).where(
            ConceptRelation.relation_type == "PREREQUISITE",
            ConceptRelation.source_concept_id.in_(point_concepts.values()),
        )).all():
            # The graph labels an outgoing relation from a concept to its prerequisite.
            for source_id in concept_point_ids.get(relation.source_concept_id, set()):
                for prerequisite_id in concept_point_ids.get(relation.target_concept_id, set()):
                    concept_edges.append((source_id, prerequisite_id))
    ordered_plans, cycle_breaks = topological_learning_order(
        plans, point_prerequisites=point_prerequisites, concept_prerequisites=concept_edges,
        target_role=goal.target_role,
    )
    compile_stats["cycle_break_count"] = cycle_breaks

    units = []
    point_to_unit: dict[int, LearningUnit] = {}
    for index, plan in enumerate(ordered_plans):
        ids = plan["source_knowledge_point_ids"]
        source_points = [point for point in points if point.id in ids]
        source_points.sort(key=lambda point: (-importance_engine.goal_aware_point_importance(point, goal.name, goal.description, goal.target_role)[0], point.id))
        primary = source_points[0]
        lesson_ids = list(dict.fromkeys(point.lesson_id for point in source_points))
        course_ids = list(dict.fromkeys(lessons[lid].course_id for lid in lesson_ids if lid in lessons))
        aggregation = "MERGED_UNIT" if len(ids) > 1 else "STANDALONE_UNIT"
        relation = plan["relationship"]
        merge_type = {"MERGE_COMPLEMENTARY": "COMPLEMENTARY", "DEPTH_VARIANT": "DEPTH_LAYERED", "KEEP_SEPARATE": "NONE"}.get(relation, relation)
        unit = LearningUnit(
            goal_id=goal.id, title=plan["canonical_title"], unit_type=plan["unit_type"],
            capability_tags_json=json.dumps(capability_tags(
                plan["canonical_title"], [point.name for point in source_points]
            ), ensure_ascii=False),
            aggregation_type=aggregation, merge_type=merge_type, canonical_topic_id=plan["canonical_topic_id"],
            summary=plan["summary"], learning_objective=plan["learning_objective"],
            importance=plan["importance"], goal_relevance=plan["goal_relevance"], difficulty=plan["difficulty"],
            source_quality=plan["source_quality"], source_section_ids_json=json.dumps(list(dict.fromkeys(
                lessons[lid].section_title or lessons[lid].chapter_title or "" for lid in lesson_ids if lid in lessons
            )), ensure_ascii=False),
            primary_source_id=primary.id, supplementary_source_ids_json=json.dumps([p.id for p in source_points if p.id != primary.id]),
            estimated_minutes=max(10, 10 * len(ids)), order_index=index, primary_knowledge_point_id=primary.id,
            source_course_ids_json=json.dumps(course_ids), source_lesson_ids_json=json.dumps(lesson_ids),
            source_knowledge_point_ids_json=json.dumps(ids), status="NOT_STARTED", mastery=0,
        )
        db.add(unit)
        db.flush()
        units.append(unit)
        for point_id in ids:
            point_to_unit[point_id] = unit

    for plan, unit in zip(ordered_plans, units):
        prerequisites = set()
        for point_id in plan["source_knowledge_point_ids"]:
            for source_id, prerequisite_id in concept_edges:
                if source_id == point_id:
                    prerequisite_unit = point_to_unit.get(prerequisite_id)
                    if prerequisite_unit and prerequisite_unit.id != unit.id:
                        prerequisites.add(prerequisite_unit.id)
            for required_name in point_prerequisites.get(point_id, []):
                required_key = _normalize(required_name)
                for candidate in ordered_plans:
                    candidate_key = _normalize(candidate["canonical_title"])
                    if candidate_key and (candidate_key == required_key or (len(required_key) >= 4 and required_key in candidate_key)):
                        for required_id in candidate["source_knowledge_point_ids"]:
                            other_unit = point_to_unit.get(required_id)
                            if other_unit and other_unit.id != unit.id:
                                prerequisites.add(other_unit.id)
        unit.prerequisite_unit_ids_json = json.dumps(sorted(prerequisites))

    db.add(LearningGoalCompileReport(
        goal_id=goal.id, compile_mode=compile_mode, raw_candidate_count=compile_stats["raw_candidate_count"],
        eligible_count=compile_stats["eligible_count"], container_filtered_count=compile_stats["container_filtered_count"],
        fragment_filtered_count=compile_stats["fragment_filtered_count"], noise_filtered_count=compile_stats["noise_filtered_count"],
        normalized_topic_count=compile_stats["normalized_topic_count"], exact_duplicate_count=compile_stats["exact_duplicate_count"],
        merged_count=compile_stats["merged_count"], depth_variant_count=compile_stats["depth_variant_count"],
        kept_separate_count=compile_stats["kept_separate_count"], final_unit_count=compile_stats["final_unit_count"],
        cycle_break_count=cycle_breaks,
        api_calls=compile_stats["api_calls"], prompt_tokens=compile_stats["prompt_tokens"],
        completion_tokens=compile_stats["completion_tokens"], total_tokens=compile_stats["total_tokens"],
        failed_buckets_json=json.dumps(compile_stats["failed_buckets"], ensure_ascii=False),
        filtered_candidates_json=json.dumps(compile_stats["filtered_candidates"], ensure_ascii=False),
    ))
    db.flush()
    return units


def _unit_view(db: Session, unit: LearningUnit, importance: tuple[str, float], target_role: str) -> dict:
    course_ids = _json(unit.source_course_ids_json)
    lesson_ids = _json(unit.source_lesson_ids_json)
    point_ids = _json(unit.source_knowledge_point_ids_json)
    courses = {c.id: c for c in db.scalars(select(Course).where(Course.id.in_(course_ids))).all()} if course_ids else {}
    lessons = {l.id: l for l in db.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids))).all()} if lesson_ids else {}
    points = {p.id: p for p in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))).all()} if point_ids else {}
    sources = []
    for pid in point_ids:
        point = points.get(pid)
        lesson = lessons.get(point.lesson_id) if point else None
        if not point or not lesson:
            continue
        course = courses.get(lesson.course_id)
        sources.append({"course_id": lesson.course_id, "course_name": course.name if course else "课程已移除",
            "lesson_id": lesson.id, "lesson_title": lesson.title,
            "section_title": lesson.section_title or lesson.chapter_title,
            "knowledge_point_id": point.id, "knowledge_point_name": point.name,
            "description": point.description})
    mastery_rows = db.scalars(select(MasteryScore).where(MasteryScore.knowledge_point_id.in_(point_ids))).all() if point_ids else []
    mastery_by_id = {row.knowledge_point_id: row.mastery_score for row in mastery_rows}
    unit.mastery = round(sum(mastery_by_id.get(pid, 0) for pid in point_ids) / max(1, len(point_ids)))
    importance_level, importance_score = importance
    legacy_aggregation = unit.unit_type if unit.unit_type in {"MERGED_UNIT", "STANDALONE_UNIT"} else None
    unit_type = infer_learning_unit_type(unit.title) if legacy_aggregation else unit.unit_type
    aggregation_type = legacy_aggregation or unit.aggregation_type or ("MERGED_UNIT" if len(point_ids) > 1 else "STANDALONE_UNIT")
    phase_index, _phase_order, phase_label = learning_phase({
        "canonical_title": unit.title, "canonical_topic_id": unit.canonical_topic_id,
        "unit_type": unit_type,
    }, target_role)
    return {"id": unit.id, "title": unit.title, "unit_type": unit_type,
        "capability_tags": _json(unit.capability_tags_json) or capability_tags(
            unit.title, [point.name for point in points.values()]
        ),
        "phase_index": phase_index, "phase_label": phase_label,
        "aggregation_type": aggregation_type,
        "canonical_topic_id": unit.canonical_topic_id or "", "summary": unit.summary or "",
        "learning_objective": unit.learning_objective or "", "importance": unit.importance,
        "goal_relevance": unit.goal_relevance, "difficulty": unit.difficulty,
        "source_quality": unit.source_quality, "source_section_ids": _json(unit.source_section_ids_json),
        "primary_source_id": unit.primary_source_id,
        "supplementary_source_ids": _json(unit.supplementary_source_ids_json),
        "estimated_minutes": unit.estimated_minutes,
        "merge_type": unit.merge_type,
        "order_index": unit.order_index, "primary_knowledge_point_id": unit.primary_knowledge_point_id,
        "source_course_ids": course_ids, "source_lesson_ids": lesson_ids, "source_knowledge_point_ids": point_ids,
        "prerequisite_unit_ids": _json(unit.prerequisite_unit_ids_json), "sources": sources,
        "status": unit.status, "mastery": unit.mastery,
        "importance_level": importance_level, "importance_score": importance_score}


def goal_view(db: Session, goal: LearningGoal) -> dict:
    sources = []
    for row in db.scalars(select(GoalSource).where(GoalSource.goal_id == goal.id)).all():
        course = db.get(Course, row.course_id)
        sources.append({"id": row.id, "course_id": row.course_id, "course_name": course.name if course else "课程已移除",
            "selected_lesson_ids": _json(row.selected_lesson_ids_json), "selection_source": row.selection_source,
            "relevance_score": row.relevance_score, "status": row.status})
    units = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal.id).order_by(LearningUnit.order_index, LearningUnit.id)).all()
    point_ids = list(dict.fromkeys(point_id for unit in units for point_id in _json(unit.source_knowledge_point_ids_json)))
    points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids))).all() if point_ids else []
    point_scores = {
        point.id: importance_engine.goal_aware_point_importance(
            point, goal.name, goal.description, goal.target_role
        )[0]
        for point in points
    }
    unit_importance = {}
    for unit in units:
        scores = [point_scores[point_id] for point_id in _json(unit.source_knowledge_point_ids_json) if point_id in point_scores]
        score = importance_engine.goal_aware_unit_score(unit, scores, goal.target_role)
        level = "IMPORTANT" if score >= 4 else "SECONDARY" if score >= 3 else "OPTIONAL"
        unit_importance[unit.id] = (level, score)
    # A prerequisite inherits the strongest dependent tier so the folded
    # importance view never asks learners to study a prerequisite later.
    for _ in range(len(units)):
        changed = False
        for unit in units:
            dependent_level, dependent_score = unit_importance[unit.id]
            for prerequisite_id in _json(unit.prerequisite_unit_ids_json):
                if prerequisite_id not in unit_importance:
                    continue
                _current_level, current_score = unit_importance[prerequisite_id]
                if dependent_score > current_score:
                    unit_importance[prerequisite_id] = (dependent_level, dependent_score)
                    changed = True
        if not changed:
            break
    report = db.scalars(select(LearningGoalCompileReport).where(
        LearningGoalCompileReport.goal_id == goal.id
    ).order_by(LearningGoalCompileReport.created_at.desc(), LearningGoalCompileReport.id.desc())).first()
    report_view = None
    if report:
        report_view = {key: getattr(report, key) for key in (
            "id", "compile_mode", "status", "raw_candidate_count", "eligible_count",
            "container_filtered_count", "fragment_filtered_count", "noise_filtered_count",
            "normalized_topic_count", "exact_duplicate_count", "merged_count", "depth_variant_count",
            "kept_separate_count", "final_unit_count", "api_calls", "prompt_tokens",
            "completion_tokens", "total_tokens", "cycle_break_count", "created_at",
        )}
        report_view["failed_buckets"] = _json(report.failed_buckets_json)
        report_view["filtered_candidates"] = _json(report.filtered_candidates_json)
    return {"id": goal.id, "name": goal.name, "description": goal.description, "target_role": goal.target_role,
        "target_readiness": goal.target_readiness, "daily_minutes": goal.daily_minutes,
        "deadline": goal.deadline, "goal_snapshot": _json(goal.goal_snapshot_json),
        "creation_mode": goal.creation_mode, "status": goal.status, "sources": sources,
        "latest_compile_report": report_view,
        "units": [_unit_view(db, unit, unit_importance[unit.id], goal.target_role) for unit in units]}


def learning_unit_completion(db: Session, goal_id: int, unit_id: int, session_id: int) -> dict:
    """Return persisted completion, evaluation summary, and the next path unit."""
    goal = db.get(LearningGoal, goal_id)
    unit = db.get(LearningUnit, unit_id)
    session = db.get(LearningSession, session_id)
    if not goal or not unit or unit.goal_id != goal_id:
        raise LookupError("学习目标或学习单元不存在。")
    if not session or session.learning_unit_id != unit_id:
        raise LookupError("找不到此学习单元对应的学习会话。")

    units = db.scalars(select(LearningUnit).where(
        LearningUnit.goal_id == goal_id
    ).order_by(LearningUnit.order_index, LearningUnit.id)).all()
    completed_count = sum(item.status == "COMPLETED" for item in units)
    ordered_ids = [item.id for item in units]
    current_index = ordered_ids.index(unit_id)
    next_unit = next((item for item in units[current_index + 1:] if item.status != "COMPLETED"), None)

    evaluations = db.execute(
        select(AnswerEvaluation, QuestionAttempt)
        .join(QuestionAttempt, QuestionAttempt.id == AnswerEvaluation.question_attempt_id)
        .where(QuestionAttempt.learning_session_id == session_id)
        .order_by(QuestionAttempt.answered_at, QuestionAttempt.id)
    ).all()
    scores = [evaluation.total_score for evaluation, _attempt in evaluations]
    strengths = list(dict.fromkeys(
        text for evaluation, _attempt in evaluations
        for text in _json(evaluation.correct_points_json)
    ))[:5]
    weaknesses = list(dict.fromkeys(
        text for evaluation, _attempt in evaluations
        for field in (evaluation.missing_points_json, evaluation.incorrect_points_json,
                      evaluation.weak_concepts_json, evaluation.weak_reasoning_json,
                      evaluation.weak_product_application_json)
        for text in _json(field)
    ))[:5]

    is_complete = session.completed and unit.status == "COMPLETED"
    return {
        "goal_id": goal.id,
        "goal_name": goal.name,
        "unit_id": unit.id,
        "unit_title": unit.title,
        "completed": is_complete,
        "goal_completed": is_complete and completed_count == len(units),
        "completed_count": completed_count,
        "total_count": len(units),
        "score": round(sum(scores) / len(scores)) if scores else None,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "next_unit": ({"id": next_unit.id, "title": next_unit.title,
                       "estimated_minutes": next_unit.estimated_minutes} if next_unit else None),
    }


async def create_goal(db: Session, payload: dict) -> dict:
    sources = _validate_sources(db, payload["sources"])
    point_ids = {pid for source in sources for pid in source["knowledge_point_ids"]}
    if not point_ids:
        raise ValueError("所选课程或章节中没有可编排的知识点。")
    goal_name = payload["name"].strip()
    goal_description = payload.get("description", "").strip()
    target_role = payload.get("target_role", "general_ai_pm")
    goal = LearningGoal(name=goal_name, description=goal_description,
        target_role=target_role, target_readiness=payload.get("target_readiness", 60),
        daily_minutes=payload.get("daily_minutes", 30), deadline=payload.get("deadline"),
        goal_snapshot_json=json.dumps({"name": goal_name, "description": goal_description, "target_role": target_role}, ensure_ascii=False),
        creation_mode=payload["creation_mode"], status="ACTIVE")
    db.add(goal); db.flush()
    for source in sources:
        if not source["knowledge_point_ids"]:
            continue
        db.add(GoalSource(goal_id=goal.id, course_id=source["course_id"],
            selected_lesson_ids_json=json.dumps(source["lesson_ids"]), selection_source=source.get("selection_source", "MANUAL"),
            relevance_score=source.get("relevance_score", 0), status="INCLUDED"))
    units = await _build_units(db, goal, sources)
    if not units:
        db.rollback()
        raise ValueError("所选知识点均为课程容器或无效片段，未生成学习单元。")
    db.commit()
    db.refresh(goal)
    return goal_view(db, goal)


async def rebuild_goal(db: Session, goal_id: int) -> dict:
    """Replan a saved path while preserving source records and study sessions."""
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    old_units = db.scalars(
        select(LearningUnit).where(LearningUnit.goal_id == goal_id).order_by(LearningUnit.order_index)
    ).all()
    old_unit_ids = [unit.id for unit in old_units]
    old_point_ids = {
        unit.id: set(_json(unit.source_knowledge_point_ids_json)) for unit in old_units
    }
    point_ids = list(dict.fromkeys(
        point_id for unit in old_units for point_id in _json(unit.source_knowledge_point_ids_json)
    ))
    points = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids)).order_by(KnowledgePoint.id)
    ).all() if point_ids else []
    if not points:
        raise ValueError("当前目标没有可重新编排的来源知识点。")

    lesson_map = {
        lesson.id: lesson
        for lesson in db.scalars(
            select(Lesson).where(Lesson.id.in_({point.lesson_id for point in points}))
        ).all()
    }
    goal_sources = {
        source.course_id: source
        for source in db.scalars(select(GoalSource).where(GoalSource.goal_id == goal_id)).all()
    }
    grouped: dict[int, dict] = {}
    for point in points:
        lesson = lesson_map.get(point.lesson_id)
        if not lesson:
            continue
        source = grouped.setdefault(lesson.course_id, {
            "course_id": lesson.course_id, "lesson_ids": set(), "knowledge_point_ids": [],
        })
        source["lesson_ids"].add(lesson.id)
        source["knowledge_point_ids"].append(point.id)
    sources = []
    for course_id, source in grouped.items():
        existing = goal_sources.get(course_id)
        sources.append({
            **source,
            "lesson_ids": sorted(source["lesson_ids"]),
            "knowledge_point_ids": source["knowledge_point_ids"],
            "selection_source": existing.selection_source if existing else "REBUILD",
            "relevance_score": existing.relevance_score if existing else 0,
        })
    if not sources:
        raise ValueError("当前目标的原始课程来源已不可用，无法重新编排。")

    try:
        new_units = await _build_units(db, goal, sources)
        if not new_units:
            raise ValueError("没有生成新的学习单元，原路径保持不变。")

        point_to_new_unit = {
            point_id: unit
            for unit in new_units
            for point_id in _json(unit.source_knowledge_point_ids_json)
        }
        latest_report = db.scalars(select(LearningGoalCompileReport).where(
            LearningGoalCompileReport.goal_id == goal_id
        ).order_by(LearningGoalCompileReport.id.desc())).first()
        filtered_ids = {
            item["knowledge_point_id"]
            for item in _json(latest_report.filtered_candidates_json)
            if latest_report and isinstance(item, dict) and "knowledge_point_id" in item
        }
        eligible_ids = {point.id for point in points} - filtered_ids
        compiled_ids = [pid for unit in new_units for pid in _json(unit.source_knowledge_point_ids_json)]
        if set(point_to_new_unit) != eligible_ids or len(compiled_ids) != len(set(compiled_ids)):
            raise ValueError("新路径未精确覆盖所有合格来源知识点，已取消重编排。")

        progress_rank = {"NOT_STARTED": 0, "IN_PROGRESS": 1, "COMPLETED": 2}
        point_progress = {}
        for old_unit in old_units:
            rank = progress_rank.get(old_unit.status, 0)
            for point_id in old_point_ids[old_unit.id]:
                if rank > progress_rank.get(point_progress.get(point_id, "NOT_STARTED"), 0):
                    point_progress[point_id] = old_unit.status
        for unit in new_units:
            unit_points = _json(unit.source_knowledge_point_ids_json)
            statuses = [point_progress.get(point_id, "NOT_STARTED") for point_id in unit_points]
            if statuses and all(status == "COMPLETED" for status in statuses):
                unit.status = "COMPLETED"
            elif any(status != "NOT_STARTED" for status in statuses):
                unit.status = "IN_PROGRESS"

        sessions = db.scalars(
            select(LearningSession).where(LearningSession.learning_unit_id.in_(old_unit_ids))
        ).all() if old_unit_ids else []
        new_order = {unit.id: unit.order_index for unit in new_units}
        for session in sessions:
            if session.current_knowledge_point_id in point_to_new_unit:
                session.learning_unit_id = point_to_new_unit[session.current_knowledge_point_id].id
                continue
            if session.current_knowledge_point_id in filtered_ids:
                session.learning_unit_id = None
                continue
            session_point_ids = set(_json(session.knowledge_point_ids_json))
            session_point_ids.update(old_point_ids.get(session.learning_unit_id, set()))
            overlap_count = {}
            for point_id in session_point_ids:
                unit = point_to_new_unit.get(point_id)
                if unit:
                    overlap_count[unit.id] = overlap_count.get(unit.id, 0) + 1
            session.learning_unit_id = (
                max(overlap_count, key=lambda unit_id: (overlap_count[unit_id], -new_order[unit_id]))
                if overlap_count else None
            )
        db.flush()
        for old_unit in old_units:
            db.delete(old_unit)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(goal)
    return goal_view(db, goal)


def refresh_saved_goal_order(db: Session, goal_id: int) -> dict:
    """Reorder an already compiled path locally; never rescan courses or call an LLM."""
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    units = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id)).all()
    by_id = {unit.id: unit for unit in units}
    plans = []
    for unit in units:
        required_points = [
            by_id[unit_id].primary_knowledge_point_id
            for unit_id in _json(unit.prerequisite_unit_ids_json)
            if unit_id in by_id and by_id[unit_id].primary_knowledge_point_id is not None
        ]
        plans.append({
            "canonical_title": unit.title,
            "canonical_topic_id": unit.canonical_topic_id,
            "unit_type": unit.unit_type,
            "source_knowledge_point_ids": _json(unit.source_knowledge_point_ids_json),
            "prerequisite_knowledge_point_ids": required_points,
            "goal_relevance": unit.goal_relevance,
            "importance": unit.importance,
            "difficulty": unit.difficulty,
            "mastery": unit.mastery,
            "source_quality": unit.source_quality,
            "unit_id": unit.id,
        })
    ordered, cycle_breaks = topological_learning_order(plans, target_role=goal.target_role)
    for index, plan in enumerate(ordered):
        by_id[plan["unit_id"]].order_index = index
    if not _json(goal.goal_snapshot_json):
        goal.goal_snapshot_json = json.dumps({
            "name": goal.name, "description": goal.description,
            "target_role": goal.target_role, "target_readiness": goal.target_readiness,
            "daily_minutes": goal.daily_minutes, "deadline": str(goal.deadline) if goal.deadline else None,
        }, ensure_ascii=False)
    db.commit()
    return {"unit_count": len(units), "cycle_break_count": cycle_breaks}


def merge_exact_saved_goal_duplicates(db: Session, goal_id: int) -> dict:
    """Coalesce only same-title, same-topic, same-type units; preserve study links."""
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    units = db.scalars(select(LearningUnit).where(
        LearningUnit.goal_id == goal_id
    ).order_by(LearningUnit.order_index, LearningUnit.id)).all()
    primary_by_key: dict[tuple[str, str, str], LearningUnit] = {}
    replacement: dict[int, int] = {}
    for unit in units:
        key = (unit.canonical_topic_id, normalize_learning_topic_title(unit.title), unit.unit_type)
        primary = primary_by_key.setdefault(key, unit)
        if primary.id == unit.id:
            continue
        if primary.id in _json(unit.prerequisite_unit_ids_json) or unit.id in _json(primary.prerequisite_unit_ids_json):
            continue
        for field in (
            "source_course_ids_json", "source_lesson_ids_json", "source_section_ids_json",
            "source_knowledge_point_ids_json", "supplementary_source_ids_json",
            "prerequisite_unit_ids_json",
        ):
            values = list(dict.fromkeys(_json(getattr(primary, field)) + _json(getattr(unit, field))))
            setattr(primary, field, json.dumps(values, ensure_ascii=False))
        primary.supplementary_source_ids_json = json.dumps(list(dict.fromkeys(
            _json(primary.supplementary_source_ids_json) + [
                point_id for point_id in _json(primary.source_knowledge_point_ids_json)
                if point_id != primary.primary_knowledge_point_id
            ]
        )))
        primary.capability_tags_json = json.dumps(list(dict.fromkeys(
            _json(primary.capability_tags_json) + _json(unit.capability_tags_json)
            + capability_tags(primary.title)
        )), ensure_ascii=False)
        primary.aggregation_type = "MERGED_UNIT"
        primary.merge_type = "EXACT_DUPLICATE"
        primary.importance = max(primary.importance, unit.importance)
        primary.goal_relevance = max(primary.goal_relevance, unit.goal_relevance)
        primary.source_quality = max(primary.source_quality, unit.source_quality)
        primary.mastery = max(primary.mastery, unit.mastery)
        if unit.status != "NOT_STARTED" and primary.status == "NOT_STARTED":
            primary.status = "IN_PROGRESS"
        replacement[unit.id] = primary.id
        db.query(LearningSession).filter(LearningSession.learning_unit_id == unit.id).update(
            {LearningSession.learning_unit_id: primary.id}, synchronize_session=False
        )
        db.delete(unit)
    if not replacement:
        return {"merged_unit_count": 0, "unit_count": len(units)}
    for unit in units:
        if unit.id in replacement:
            continue
        prerequisites = [replacement.get(unit_id, unit_id) for unit_id in _json(unit.prerequisite_unit_ids_json)]
        unit.prerequisite_unit_ids_json = json.dumps(sorted(set(prerequisites) - {unit.id}))
    remaining = [unit for unit in units if unit.id not in replacement]
    for index, unit in enumerate(sorted(remaining, key=lambda row: (row.order_index, row.id))):
        unit.order_index = index
    latest_report = db.scalars(select(LearningGoalCompileReport).where(
        LearningGoalCompileReport.goal_id == goal_id
    ).order_by(LearningGoalCompileReport.id.desc())).first()
    if latest_report:
        latest_report.final_unit_count = len(remaining)
        latest_report.exact_duplicate_count += len(replacement)
    db.commit()
    return {"merged_unit_count": len(replacement), "unit_count": len(remaining)}


async def reconcile_saved_goal_topic(
    db: Session, goal_id: int, topic_id: str, *, commit: bool = True
) -> dict:
    """Reconcile one small saved topic from unit abstracts, retaining every source reference."""
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    units = db.scalars(select(LearningUnit).where(
        LearningUnit.goal_id == goal_id, LearningUnit.canonical_topic_id == topic_id
    ).order_by(LearningUnit.order_index, LearningUnit.id)).all()
    if not 2 <= len(units) <= 24:
        raise ValueError("单主题复核只接受 2–24 个现有单元。")
    payload = {"goal": {"name": goal.name, "description": goal.description,
        "target_role": goal.target_role}, "topic_bucket": topic_id,
        "candidates": [{"id": unit.id, "title": unit.title, "description": (unit.summary or "")[:180],
            "unit_type": unit.unit_type, "source_count": len(_json(unit.source_knowledge_point_ids_json))}
            for unit in units]}
    system = (
        "你是学习路径去重审校员。根据输入标题和短摘要识别重复及互补内容，每个候选ID恰好出现一次。"
        "同一学习目标的定义、作用和背景可合为概念单元；同一主题的能力、特点与应用可合为互补单元。"
        "RAG基本定义和解决问题可合并，架构和工作流程可合并；评估、选型、检索工程细节必须分开。"
        "不同深度标记DEPTH_VARIANT并分别保留。项目案例绝不与概念合并。不要为了减少数量而合并不同学习目标。"
        "仅使用EXACT_DUPLICATE、MERGE_COMPLEMENTARY、DEPTH_VARIANT、KEEP_SEPARATE。标题简短，summary只能归纳输入摘要。"
        "prerequisite_candidate_ids必须是本次候选ID，表示被依赖的前置项。"
    )
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    def on_call():
        usage["calls"] += 1
    def on_usage(prompt: int, completion: int):
        usage["prompt_tokens"] += prompt
        usage["completion_tokens"] += completion
    output = await llm_service.complete_structured(
        BucketCompileOutput, system, json.dumps(payload, ensure_ascii=False),
        fallback=lambda: BucketCompileOutput(units=[]), retries=0, max_tokens=4000,
        on_api_call=on_call, on_usage=on_usage,
    )
    seen = [unit_id for proposal in output.units for unit_id in proposal.candidate_ids]
    expected = {unit.id for unit in units}
    if set(seen) != expected or len(seen) != len(set(seen)):
        raise ValueError("模型未完整覆盖本主题全部单元，未保存编排结果。")
    unit_by_id = {unit.id: unit for unit in units}
    for proposal in output.units:
        if len(proposal.candidate_ids) < 2 or proposal.relationship not in {"EXACT_DUPLICATE", "MERGE_COMPLEMENTARY"}:
            continue
        group = [unit_by_id[unit_id] for unit_id in proposal.candidate_ids]
        if len({unit.unit_type for unit in group}) != 1 or any(unit.unit_type == "PROJECT_CASE" for unit in group):
            raise ValueError("模型提议跨类型或项目案例合并，已拒绝整批结果。")
        group_ids = {unit.id for unit in group}
        if any(group_ids.intersection(_json(unit.prerequisite_unit_ids_json)) for unit in group):
            raise ValueError("模型提议合并存在前置关系的单元，已拒绝整批结果。")
    replacement: dict[int, int] = {}
    try:
        for proposal in output.units:
            if len(proposal.candidate_ids) < 2 or proposal.relationship not in {"EXACT_DUPLICATE", "MERGE_COMPLEMENTARY"}:
                continue
            group = [unit_by_id[unit_id] for unit_id in proposal.candidate_ids]
            primary = min(group, key=lambda unit: (unit.order_index, unit.id))
            for other in group:
                if other.id == primary.id:
                    continue
                for field in ("source_course_ids_json", "source_lesson_ids_json", "source_section_ids_json",
                    "source_knowledge_point_ids_json", "supplementary_source_ids_json"):
                    combined = list(dict.fromkeys(_json(getattr(primary, field)) + _json(getattr(other, field))))
                    setattr(primary, field, json.dumps(combined, ensure_ascii=False))
                replacement[other.id] = primary.id
                db.query(LearningSession).filter(LearningSession.learning_unit_id == other.id).update(
                    {LearningSession.learning_unit_id: primary.id}, synchronize_session=False)
                if other.status != "NOT_STARTED" and primary.status == "NOT_STARTED":
                    primary.status = "IN_PROGRESS"
                primary.mastery = max(primary.mastery, other.mastery)
                primary.importance = max(primary.importance, other.importance)
                primary.goal_relevance = max(primary.goal_relevance, other.goal_relevance)
                primary.source_quality = max(primary.source_quality, other.source_quality)
                db.delete(other)
            primary.title = proposal.canonical_title[:100]
            primary.capability_tags_json = json.dumps(capability_tags(
                primary.title, [point.name for point in db.scalars(
                    select(KnowledgePoint).where(KnowledgePoint.id.in_(
                        _json(primary.source_knowledge_point_ids_json)
                    ))
                ).all()]
            ), ensure_ascii=False)
            primary.summary = proposal.summary[:800]
            primary.learning_objective = proposal.learning_objective[:400]
            primary.aggregation_type = "MERGED_UNIT"
            primary.merge_type = proposal.relationship
            primary.supplementary_source_ids_json = json.dumps(list(dict.fromkeys(
                _json(primary.supplementary_source_ids_json) + [point_id for point_id in
                    _json(primary.source_knowledge_point_ids_json) if point_id != primary.primary_knowledge_point_id]
            )))
        if replacement:
            db.flush()
            for unit in db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id)).all():
                prereqs = [replacement.get(unit_id, unit_id) for unit_id in _json(unit.prerequisite_unit_ids_json)]
                unit.prerequisite_unit_ids_json = json.dumps(sorted(set(prereqs) - {unit.id}))
            remaining = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id)).all()
            for index, unit in enumerate(sorted(remaining, key=lambda row: (row.order_index, row.id))):
                unit.order_index = index
        latest = db.scalars(select(LearningGoalCompileReport).where(
            LearningGoalCompileReport.goal_id == goal_id
        ).order_by(LearningGoalCompileReport.id.desc())).first()
        if latest:
            latest.api_calls += usage["calls"]
            latest.prompt_tokens += usage["prompt_tokens"]
            latest.completion_tokens += usage["completion_tokens"]
            latest.total_tokens = latest.prompt_tokens + latest.completion_tokens
            latest.merged_count += sum(max(0, len(proposal.candidate_ids) - 1)
                for proposal in output.units if proposal.relationship == "MERGE_COMPLEMENTARY")
            latest.exact_duplicate_count += sum(max(0, len(proposal.candidate_ids) - 1)
                for proposal in output.units if proposal.relationship == "EXACT_DUPLICATE")
            latest.final_unit_count = db.query(LearningUnit).filter(LearningUnit.goal_id == goal_id).count()
        db.flush()
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    return {"topic_id": topic_id, "merged_unit_count": len(replacement),
        "remaining_unit_count": len(units) - len(replacement), "usage": usage}


async def incremental_compile_goal(db: Session, goal_id: int, course_ids: list[int]) -> dict:
    """Compile only selected courses not already attached to this goal."""
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    existing_sources = db.scalars(select(GoalSource).where(GoalSource.goal_id == goal_id)).all()
    existing_course_ids = {source.course_id for source in existing_sources}
    selected_ids = list(dict.fromkeys(course_ids))
    if not selected_ids:
        raise ValueError("请选择至少一门新课程。")
    if set(selected_ids) & existing_course_ids:
        raise ValueError("增量编排只接受尚未加入该目标的课程；已有课程不会重复扫描。")
    try:
        sources = []
        for course_id in selected_ids:
            course = db.get(Course, course_id)
            if not course:
                raise ValueError(f"课程 {course_id} 不存在。")
            lessons = db.scalars(select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.id)).all()
            points = db.scalars(select(KnowledgePoint).join(Lesson).where(
                Lesson.course_id == course_id, KnowledgePoint.category.notin_(["Section", "PDF Section", "Retired"])
            ).order_by(KnowledgePoint.id)).all()
            if not points:
                raise ValueError(f"课程“{course.name}”没有可编排的知识点。")
            sources.append({"course_id": course_id, "lesson_ids": [lesson.id for lesson in lessons],
                "knowledge_point_ids": [point.id for point in points], "selection_source": "INCREMENTAL",
                "relevance_score": 0})

        old_units = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id)).all()
        compiled = await _build_units(db, goal, sources, compile_mode="INCREMENTAL")
        if not compiled:
            raise ValueError("新课程未生成合格学习单元，目标保持不变。")

        # Deterministically merge exact title matches with prior units. Existing
        # course knowledge points are only read as titles; they are never sent to the LLM.
        old_points_ids = {pid for unit in old_units for pid in _json(unit.source_knowledge_point_ids_json)}
        old_points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(old_points_ids))).all() if old_points_ids else []
        old_point_keys: dict[str, LearningUnit] = {}
        for unit in old_units:
            old_point_keys[normalize_learning_topic_title(unit.title)] = unit
            for point in old_points:
                if point.id in _json(unit.source_knowledge_point_ids_json):
                    old_point_keys.setdefault(normalize_learning_topic_title(point.name), unit)
        point_map = {point.id: point for point in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_([pid for unit in compiled for pid in _json(unit.source_knowledge_point_ids_json)])
        )).all()}
        exact_merge_count = 0
        for unit in list(compiled):
            new_point_ids = _json(unit.source_knowledge_point_ids_json)
            matches = [old_point_keys.get(normalize_learning_topic_title(point_map[pid].name)) for pid in new_point_ids if pid in point_map]
            target = next((candidate for candidate in matches if candidate is not None), None)
            if not target:
                continue
            target_points = list(dict.fromkeys(_json(target.source_knowledge_point_ids_json) + new_point_ids))
            target_courses = list(dict.fromkeys(_json(target.source_course_ids_json) + _json(unit.source_course_ids_json)))
            target_lessons = list(dict.fromkeys(_json(target.source_lesson_ids_json) + _json(unit.source_lesson_ids_json)))
            target.source_knowledge_point_ids_json = json.dumps(target_points)
            target.capability_tags_json = json.dumps(list(dict.fromkeys(
                _json(target.capability_tags_json) + _json(unit.capability_tags_json)
                + capability_tags(target.title)
            )), ensure_ascii=False)
            target.source_course_ids_json = json.dumps(target_courses)
            target.source_lesson_ids_json = json.dumps(target_lessons)
            target.prerequisite_unit_ids_json = json.dumps(list(dict.fromkeys(
                _json(target.prerequisite_unit_ids_json) + _json(unit.prerequisite_unit_ids_json)
            )))
            target.supplementary_source_ids_json = json.dumps(list(dict.fromkeys(
                _json(target.supplementary_source_ids_json) + [pid for pid in new_point_ids if pid != target.primary_source_id]
            )))
            target.aggregation_type = "MERGED_UNIT"
            target.merge_type = "EXACT_DUPLICATE"
            target.importance = max(target.importance, unit.importance)
            target.goal_relevance = max(target.goal_relevance, unit.goal_relevance)
            db.delete(unit)
            compiled.remove(unit)
            exact_merge_count += 1

        for source in sources:
            db.add(GoalSource(goal_id=goal.id, course_id=source["course_id"],
                selected_lesson_ids_json=json.dumps(source["lesson_ids"]), selection_source="INCREMENTAL",
                relevance_score=0, status="INCLUDED"))

        existing_topics = {unit.canonical_topic_id for unit in old_units}
        new_topics = {unit.canonical_topic_id for unit in compiled} - {""}
        reconciled_topics = []
        for topic_id in sorted(existing_topics & new_topics):
            try:
                await reconcile_saved_goal_topic(db, goal_id, topic_id, commit=False)
                reconciled_topics.append(topic_id)
            except (RuntimeError, ValueError, TypeError, KeyError):
                # New units remain valid even when a topic reconciliation fails.
                continue

        db.flush()
        all_units = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id).order_by(LearningUnit.id)).all()
        all_point_ids = list(dict.fromkeys(pid for unit in all_units for pid in _json(unit.source_knowledge_point_ids_json)))
        all_points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(all_point_ids))).all() if all_point_ids else []
        point_prerequisites = {point.id: [part.strip() for part in re.split(r"[,，、;；\n]", point.prerequisite or "") if part.strip()] for point in all_points}
        unit_by_id = {unit.id: unit for unit in all_units}
        prerequisite_points = {
            unit.id: [point_id for prerequisite_id in _json(unit.prerequisite_unit_ids_json)
                if prerequisite_id in unit_by_id
                for point_id in _json(unit_by_id[prerequisite_id].source_knowledge_point_ids_json)]
            for unit in all_units
        }
        plans = [{"canonical_title": unit.title, "canonical_topic_id": unit.canonical_topic_id,
            "unit_type": unit.unit_type,
            "source_knowledge_point_ids": _json(unit.source_knowledge_point_ids_json),
            "prerequisite_knowledge_point_ids": prerequisite_points[unit.id], "goal_relevance": unit.goal_relevance,
            "importance": unit.importance, "difficulty": unit.difficulty, "mastery": unit.mastery,
            "source_quality": unit.source_quality, "prerequisite_names": []} for unit in all_units]
        ordered, cycle_breaks = topological_learning_order(
            plans, point_prerequisites=point_prerequisites, target_role=goal.target_role
        )
        unit_by_source_key = {tuple(sorted(_json(unit.source_knowledge_point_ids_json))): unit for unit in all_units}
        ordered_units = [unit_by_source_key[tuple(sorted(plan["source_knowledge_point_ids"]))] for plan in ordered]
        title_keys = [(normalize_learning_topic_title(unit.title), unit) for unit in ordered_units]
        for order_index, unit in enumerate(ordered_units):
            unit.order_index = order_index
            prerequisites = set(_json(unit.prerequisite_unit_ids_json))
            for pid in _json(unit.source_knowledge_point_ids_json):
                for name in point_prerequisites.get(pid, []):
                    key = normalize_learning_topic_title(name)
                    for candidate_key, candidate_unit in title_keys:
                        if candidate_unit.id != unit.id and (candidate_key == key or (len(key) >= 4 and key in candidate_key)):
                            prerequisites.add(candidate_unit.id)
            unit.prerequisite_unit_ids_json = json.dumps(sorted(prerequisites))

        report = db.scalars(select(LearningGoalCompileReport).where(
            LearningGoalCompileReport.goal_id == goal_id
        ).order_by(LearningGoalCompileReport.id.desc())).first()
        if report:
            report.final_unit_count = len(all_units)
            report.exact_duplicate_count += exact_merge_count
            report.merged_count += exact_merge_count
            report.cycle_break_count = cycle_breaks
            report.status = "COMPLETED"
            report.failed_buckets_json = json.dumps(list(dict.fromkeys(
                _json(report.failed_buckets_json) + [topic for topic in sorted(existing_topics & new_topics)
                    if topic not in reconciled_topics]
            )), ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(goal)
    return goal_view(db, goal)


def reorder(db: Session, goal_id: int, unit_ids: list[int]) -> dict:
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    units = db.scalars(select(LearningUnit).where(LearningUnit.goal_id == goal_id)).all()
    if set(unit_ids) != {unit.id for unit in units} or len(unit_ids) != len(units):
        raise ValueError("排序必须包含该目标下全部学习单元，且不能重复。")
    positions = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    for unit in units:
        for prerequisite_id in _json(unit.prerequisite_unit_ids_json):
            if prerequisite_id in positions and positions[prerequisite_id] > positions[unit.id]:
                raise ValueError(f"不能将“{unit.title}”排在其前置单元之后。")
    for index, unit_id in enumerate(unit_ids):
        next(unit for unit in units if unit.id == unit_id).order_index = index
    db.commit()
    return goal_view(db, goal)


def delete_goal(db: Session, goal_id: int) -> None:
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise LookupError("学习目标不存在。")
    unit_ids = list(db.scalars(select(LearningUnit.id).where(LearningUnit.goal_id == goal_id)).all())
    if unit_ids:
        db.query(LearningSession).filter(LearningSession.learning_unit_id.in_(unit_ids)).update(
            {LearningSession.learning_unit_id: None}, synchronize_session=False
        )
    db.delete(goal)
    db.commit()
