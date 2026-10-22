"""Deterministic and bucket-scoped compilation primitives for learning goals."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field

Eligibility = Literal[
    "LEARNABLE", "SECTION_CONTAINER", "COURSE_CONTAINER", "EVIDENCE_ONLY", "NOISE", "FRAGMENT"
]
Relationship = Literal[
    "EXACT_DUPLICATE", "MERGE_COMPLEMENTARY", "DEPTH_VARIANT", "KEEP_SEPARATE"
]
UnitKind = Literal["CONCEPT", "METHOD", "PRODUCT_SKILL", "PROJECT_CASE", "EVALUATION", "TOOL"]

_CONTAINER_CATEGORIES = {
    "section", "pdf section", "retired", "课程章节", "课程章节容器", "章节容器", "课程目录"
}
_CONTAINER_NAME_MARKERS = (
    "目录", "课程总览", "课程介绍", "课程大纲", "本课程", "课程目标", "课程章节", "课程目录"
)
_FRAGMENT_STARTS = (
    "年开始", "从年开始", "因此我们", "这也意味着", "并且在这个过程中", "而在此时"
)
_DISTINCTIVE_SUBTOPICS = (
    "评估", "评价", "指标", "benchmark", "架构", "流程", "工作流", "训练", "工程", "选型",
    "vs", "项目", "案例", "优势", "原理", "应用", "机制", "检索", "召回", "重排", "chunk", "切块",
)


def normalize_learning_topic_title(value: str) -> str:
    """Normalize a title for candidate bucketing; this does not imply a merge."""
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    text = re.sub(r"^\s*(?:(?:第)?[0-9一二三四五六七八九十]+(?:[.-][0-9]+)*[、.．:：\-]?\s*)+", "", text)
    text = re.sub(r"^(?:第[一二三四五六七八九十]+节[：:]?|第一节[：:]?)", "", text)
    text = re.sub(r"^(?:什么是|什么叫|简介[:：]?|概述[:：]?)", "", text)
    text = re.sub(r"(?:简介|概述|总结|教程|课程|是什么|是什么？|是什么\?)$", "", text)
    text = "".join(char for char in text if unicodedata.category(char) not in {"So", "Sk"})
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text)


def evaluate_learning_unit_eligibility(
    *,
    name: str,
    description: str = "",
    category: str = "",
    lesson_title: str = "",
    course_name: str = "",
    source_evidence: str = "",
) -> tuple[Eligibility, str]:
    """Reject structural rows and obvious text fragments without deleting sources."""
    clean_name = unicodedata.normalize("NFKC", name or "").strip()
    category_key = unicodedata.normalize("NFKC", category or "").strip().casefold()
    description = (description or "").strip()
    evidence = (source_evidence or description).strip()
    if not clean_name:
        return "NOISE", "empty_title"
    if category_key == "retired":
        return "NOISE", "retired_knowledge_point"
    normalized = normalize_learning_topic_title(clean_name)
    if len(normalized) < 2:
        return "NOISE", "title_has_no_topic"
    if any(marker in clean_name for marker in _CONTAINER_NAME_MARKERS) and len(clean_name) < 36:
        return ("SECTION_CONTAINER" if category_key in _CONTAINER_CATEGORIES else "COURSE_CONTAINER"), "course_or_section_heading"
    if category_key == "pdf section" and ("course outline" in f"{clean_name} {description}".casefold() or "课程大纲" in clean_name[:100]):
        return "SECTION_CONTAINER", "pdf_course_outline"
    name_key = normalize_learning_topic_title(clean_name)
    lesson_key = normalize_learning_topic_title(lesson_title)
    course_key = normalize_learning_topic_title(course_name)
    if name_key and name_key == course_key and len(description) < 100:
        return "COURSE_CONTAINER", "title_only_matches_course"
    if name_key and name_key == lesson_key and course_key.startswith(name_key) and len(description) < 100:
        return "COURSE_CONTAINER", "course_cover_page"
    if ("文件下载" in clean_name or "待开放" in description[:120] or
            ("点击下方链接" in description and len(description) < 400)):
        return "EVIDENCE_ONLY", "navigation_or_download_page"
    if any(clean_name.startswith(marker) for marker in _FRAGMENT_STARTS):
        return "FRAGMENT", "sentence_fragment_prefix"
    if re.match(r"^(?:\d{4}年|年开始|年\s*\d{1,2}\s*月|从\d{4}年|从年开始)", clean_name):
        return "FRAGMENT", "orphaned_date_sentence"
    has_topic_signal = any(
        marker in clean_name.casefold()
        for marker in (*_DISTINCTIVE_SUBTOPICS, "模型", "产品", "agent", "大语言", "llm", "prompt", "rag", "transformer")
    )
    if len(clean_name) >= 72 and re.search(r"[。！？!?]", clean_name) and not has_topic_signal:
        return "FRAGMENT", "long_sentence_without_topic"
    if not evidence:
        return "EVIDENCE_ONLY", "no_source_evidence"
    if len(clean_name) > 110 and re.search(r"[。！？!?]", clean_name) and len(description) < 160:
        return "FRAGMENT", "paragraph_extracted_as_title"
    return "LEARNABLE", "has_topic_and_source_evidence"


def learning_topic_bucket(value: str, *, category: str = "", concept_names: list[str] | None = None) -> str:
    """Assign a candidate to a narrow topic bucket; buckets are not merge decisions."""
    text = unicodedata.normalize("NFKC", f"{value} {category} {' '.join(concept_names or [])}").casefold()
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("RAG_EVALUATION", ("rag评估", "rag评价", "rag指标", "检索质量", "生成质量", "rag evaluation")),
        ("RAG_SELECTION", ("rag vs", "rag与sft", "rag和sft", "rag选型", "何时用rag", "rag方案")),
        ("RAG_ENGINEERING", ("chunk", "切块", "分块", "embedding", "向量", "retrieval", "检索", "召回", "rerank", "重排", "索引")),
        ("RAG_FOUNDATION", ("rag", "检索增强生成", "检索增强")),
        ("TRANSFORMER_ATTENTION", ("attention", "注意力", "transformer架构", "transformer")),
        ("FOUNDATION_MODEL", ("foundation model", "基础模型", "基座模型")),
        ("LLM", ("大语言模型", "llm", "语言模型")),
        ("PROMPT", ("prompt", "提示词", "提示工程")),
        ("AGENT_EVALUATION", ("agent评估", "agent benchmark", "智能体评估")),
        ("TOOL_MCP", ("mcp", "tool calling", "工具调用", "function calling", "cli")),
        ("AGENT", ("agent", "智能体", "workflow", "工作流")),
        ("COMPETITOR_ANALYSIS", ("竞品", "竞争分析")),
        ("REQUIREMENT_ANALYSIS", ("需求分析", "需求池", "场景拆解")),
        ("PRODUCT_DESIGN", ("产品设计", "原型", "产品经理", "产品思维", "pr d", "prd")),
        ("EVALUATION", ("评估", "评价", "指标", "benchmark")),
        ("PROJECT_CASE", ("项目", "案例", "方案pdf", "产品方案")),
    )
    for bucket, keywords in checks:
        if any(keyword in text for keyword in keywords):
            return bucket
    key = normalize_learning_topic_title(value)
    return f"TOPIC:{key[:48] or 'OTHER'}"


def infer_learning_unit_type(title: str, category: str = "") -> UnitKind:
    text = unicodedata.normalize("NFKC", f"{title} {category}").casefold()
    if any(word in text for word in ("项目", "案例", "方案", "project", "case study")):
        return "PROJECT_CASE"
    if any(word in text for word in ("评估", "评价", "指标", "benchmark", "评测")):
        return "EVALUATION"
    if any(word in text for word in ("工具", "tool", "mcp", "cli", "平台", "软件")):
        return "TOOL"
    if any(word in text for word in ("流程", "方法", "分析", "策略", "设计", "方法论")):
        return "METHOD" if not any(word in text for word in ("产品设计", "需求分析", "原型")) else "PRODUCT_SKILL"
    if any(word in text for word in ("产品", "需求", "原型", "竞品", "教育", "教学")):
        return "PRODUCT_SKILL"
    return "CONCEPT"


def learning_phase(unit: dict, target_role: str = "general_ai_pm") -> tuple[int, int, str]:
    """Locate a unit in a prerequisite-friendly path, without forcing absent phases."""
    title = unicodedata.normalize("NFKC", unit.get("canonical_title", "")).casefold()
    topic = unit.get("canonical_topic_id", "")
    kind = unit.get("unit_type", "")
    education_role = target_role == "ai_education_pm"
    if kind == "PROJECT_CASE" or any(word in title for word in ("项目实践", "项目案例", "实战项目")):
        return 7, 0, "项目实践与案例"
    is_agent = topic in {"AGENT", "AGENT_EVALUATION", "TOOL_MCP"} or any(
        word in title for word in ("agent", "智能体", "workflow", "dify", "mcp", "claude code", "codex", "harness")
    )
    is_rag = topic.startswith("RAG_") or "rag" in title or "检索增强" in title
    is_rag_eval = topic == "RAG_EVALUATION" or (is_rag and any(word in title for word in ("评估", "评测", "指标")))
    if target_role == "ai_agent_pm":
        if is_agent:
            subrank = 0 if any(word in title for word in ("定义", "基础", "是什么")) else 2 if topic in {"TOOL_MCP", "AGENT_EVALUATION"} else 1
            return 3, subrank, "Agent 架构与任务设计"
        if is_rag_eval:
            return 5, 1, "Agent 评估与可靠性"
        if is_rag:
            return 4, 0 if any(word in title for word in ("基础", "核心思想", "是什么", "解决的问题")) else 1, "Agent 所需的 RAG 能力"
        if kind == "EVALUATION" or topic == "EVALUATION":
            return 5, 0, "Agent 评估与可靠性"
    elif target_role == "rag_enterprise_pm":
        if is_rag_eval:
            return 4, 0, "RAG 质量与分段评估"
        if is_rag:
            subrank = 0 if topic in {"RAG_FOUNDATION", "RAG_SELECTION"} else 1
            return 2 if topic in {"RAG_FOUNDATION", "RAG_SELECTION"} else 3, subrank, "企业知识库与检索工程"
        if is_agent:
            return 5, 0, "问答工作流与工具接入"
    elif target_role == "llm_application_pm":
        if is_rag_eval:
            return 5, 0, "应用评估与上线权衡"
        if is_rag:
            return 3 if topic in {"RAG_FOUNDATION", "RAG_SELECTION"} else 4, 0, "Prompt、RAG 与应用工程"
        if is_agent:
            return 6, 0, "Agent 应用专题"
    elif target_role == "algorithm_pm":
        if any(word in title for word in ("机器学习", "特征工程", "推荐", "排序", "分类模型", "回归模型", "算法模型")):
            return 2, 0, "机器学习与算法产品"
        if is_rag or is_agent:
            return 4, 0, "生成式 AI 应用专题"
        if kind == "EVALUATION" or topic == "EVALUATION" or "评估" in title:
            return 3, 0, "算法评估与实验"
    if topic == "RAG_EVALUATION" or (("rag" in title or topic == "RAG_ENGINEERING") and any(word in title for word in ("评估", "评测", "指标"))):
        return 4, 0, "RAG 评估"
    if topic.startswith("RAG_") or "rag" in title or "检索增强" in title:
        subrank = (0 if any(word in title for word in ("基础", "定义", "核心思想", "是什么", "解决的问题"))
            else 3 if topic == "RAG_SELECTION" else 2 if topic == "RAG_ENGINEERING" else 1)
        return 3, subrank, "RAG 原理与应用"
    if topic in {"AGENT", "AGENT_EVALUATION", "TOOL_MCP"} or any(word in title for word in ("agent", "智能体", "workflow", "dify", "mcp", "claude code", "codex", "harness")):
        subrank = 0 if any(word in title for word in ("定义", "基础", "是什么")) else 2 if topic in {"TOOL_MCP", "AGENT_EVALUATION"} else 1
        return 5, subrank, "Agent、Workflow 与工具"
    if topic == "PROMPT" or any(word in title for word in ("prompt", "提示词", "few-shot", "few shot")):
        return 2, 0, "Prompt 与通用评估"
    if education_role and any(word in title for word in ("教育产品", "学习效果", "产品从设计到上线的效果评估")):
        return 6, 0, "AI+教育产品场景"
    if kind == "EVALUATION" or topic == "EVALUATION" or any(word in title for word in ("模型评估", "模型评测", "benchmark")):
        return 2, 1, "Prompt 与通用评估"
    if topic in {"FOUNDATION_MODEL", "LLM", "TRANSFORMER_ATTENTION", "FINE_TUNING"} or any(
        word in title for word in ("基础模型", "大语言模型", "llm", "transformer", "预训练", "微调", "sft", "lora", "md dit", "mmdit")
    ):
        if topic == "FOUNDATION_MODEL" or "基础模型" in title:
            subrank = 0 if any(word in title for word in ("定义", "概念", "是什么")) else 1
        elif topic == "LLM" or "大语言模型" in title:
            subrank = 2
        elif "预训练" in title:
            subrank = 3
        elif "transformer" in title:
            subrank = 4 if any(word in title for word in ("概述", "架构", "基础")) else 5
        else:
            subrank = 6
        return 1, subrank, "大模型与 Transformer 基础"
    if education_role and any(word in title for word in ("教育", "教学", "学习效果", "个性化学习", "育儿", "儿童", "教师")):
        return 6, 0, "AI+教育产品场景"
    if topic in {"PRODUCT_DESIGN", "COMPETITOR_ANALYSIS", "REQUIREMENT_ANALYSIS"} or any(
        word in title for word in ("产品经理", "产品思维", "需求分析", "竞品分析", "原型", "prd")
    ):
        subrank = 0 if any(word in title for word in ("岗位", "角色", "导论", "概述", "产品思维", "核心能力")) else 2 if any(word in title for word in ("prd", "原型", "流程图")) else 1
        return 0, subrank, "AI 产品经理基础"
    return 6, 1, "岗位应用与专题"


def topological_learning_order(
    units: list[dict],
    *,
    concept_prerequisites: list[tuple[int, int]] | None = None,
    point_prerequisites: dict[int, list[str]] | None = None,
    target_role: str = "general_ai_pm",
) -> tuple[list[dict], int]:
    """Topologically order canonical units; importance only breaks ready-node ties."""
    point_to_index = {
        point_id: index
        for index, unit in enumerate(units)
        for point_id in unit.get("source_knowledge_point_ids", [])
    }
    edges: dict[int, set[int]] = {index: set() for index in range(len(units))}
    for index, unit in enumerate(units):
        for point_id in unit.get("prerequisite_knowledge_point_ids", []):
            prerequisite = point_to_index.get(point_id)
            if prerequisite is not None and prerequisite != index:
                edges[index].add(prerequisite)
    for source_point, required_point in concept_prerequisites or []:
        source = point_to_index.get(source_point)
        required = point_to_index.get(required_point)
        if source is not None and required is not None and source != required:
            edges[source].add(required)
    for index, unit in enumerate(units):
        raw_requirements = [
            normalize_learning_topic_title(value)
            for point_id in unit.get("source_knowledge_point_ids", [])
            for value in (point_prerequisites or {}).get(point_id, [])
        ]
        for requirement in raw_requirements:
            if not requirement:
                continue
            for candidate_index, candidate in enumerate(units):
                if candidate_index == index:
                    continue
                candidate_key = normalize_learning_topic_title(candidate["canonical_title"])
                if requirement == candidate_key or (len(requirement) >= 4 and requirement in candidate_key):
                    edges[index].add(candidate_index)

    def priority(index: int) -> tuple:
        unit = units[index]
        return (
            *learning_phase(unit, target_role)[:2],
            -float(unit.get("goal_relevance", 0)),
            -int(unit.get("importance", 0)),
            int(unit.get("difficulty", 1)),
            int(unit.get("mastery", 0)),
            -float(unit.get("source_quality", 0)),
            normalize_learning_topic_title(unit.get("canonical_title", "")),
            min(unit.get("source_knowledge_point_ids", [index + 1]) or [index + 1]),
        )

    remaining = set(range(len(units)))
    ordered_indices: list[int] = []
    removed_cycle_edges = 0
    while remaining:
        ready = [index for index in remaining if not (edges[index] & remaining)]
        if not ready:
            # A contradictory relation cycle has no valid topological order.
            # Break only the weakest deterministic incoming edge and report it.
            target = min(remaining, key=priority)
            blockers = [source for source in remaining if target in edges[source]]
            if not blockers:
                ready = [target]
            else:
                source = max(blockers, key=priority)
                edges[source].remove(target)
                removed_cycle_edges += 1
                continue
        chosen = min(ready, key=priority)
        ordered_indices.append(chosen)
        remaining.remove(chosen)
    return [units[index] for index in ordered_indices], removed_cycle_edges


def conservative_similarity_groups(candidates: list[dict]) -> list[list[dict]]:
    """Local fallback groups only near-identical titles, never broad topic siblings."""
    groups: list[list[dict]] = []
    for candidate in candidates:
        key = normalize_learning_topic_title(candidate.get("title", ""))
        bucket = candidate.get("bucket", "")
        distinctive = {
            marker for marker in _DISTINCTIVE_SUBTOPICS
            if marker in unicodedata.normalize("NFKC", candidate.get("title", "")).casefold()
        }
        match = None
        for group in groups:
            first = group[0]
            if first.get("bucket", "") != bucket:
                continue
            first_key = normalize_learning_topic_title(first.get("title", ""))
            first_distinctive = {
                marker for marker in _DISTINCTIVE_SUBTOPICS
                if marker in unicodedata.normalize("NFKC", first.get("title", "")).casefold()
            }
            if distinctive != first_distinctive:
                continue
            if key == first_key or (min(len(key), len(first_key)) >= 5 and SequenceMatcher(None, key, first_key).ratio() >= 0.9):
                match = group
                break
        if match is not None:
            match.append(candidate)
        else:
            groups.append([candidate])
    return groups


class CanonicalUnitPlan(BaseModel):
    canonical_title: str = Field(min_length=1, max_length=100)
    candidate_ids: list[int] = Field(min_length=1)
    unit_type: UnitKind = "CONCEPT"
    relationship: Relationship = "KEEP_SEPARATE"
    summary: str = Field(default="", max_length=800)
    learning_objective: str = Field(default="", max_length=400)
    prerequisite_candidate_ids: list[int] = Field(default_factory=list)


class BucketCompileOutput(BaseModel):
    units: list[CanonicalUnitPlan] = Field(default_factory=list)


def _exact_candidate_clusters(candidates: list[dict]) -> tuple[list[dict], int]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        key = normalize_learning_topic_title(candidate.get("title", "")) or f"id:{candidate['id']}"
        groups[key].append(candidate)
    clusters = []
    duplicate_count = 0
    for key, group in groups.items():
        group.sort(key=lambda item: (-float(item.get("source_quality", 0)), -len(item.get("description", "")), item["id"]))
        primary = dict(group[0])
        primary["id"] = min(item["id"] for item in group)
        primary["normalized_key"] = key
        primary["source_knowledge_point_ids"] = sorted(
            {point_id for item in group for point_id in item.get("source_knowledge_point_ids", [item["id"]])}
        )
        primary["description"] = "\n".join(dict.fromkeys(item.get("description", "") for item in group if item.get("description")))[:500]
        clusters.append(primary)
        duplicate_count += len(primary["source_knowledge_point_ids"]) - 1
    return clusters, duplicate_count


def _fallback_bucket(items: list[dict]) -> BucketCompileOutput:
    groups = conservative_similarity_groups(items)
    units = []
    for group in groups:
        ids = [item["id"] for item in group]
        units.append(CanonicalUnitPlan(
            canonical_title=group[0]["title"][:100],
            candidate_ids=ids,
            unit_type=group[0].get("unit_type") or infer_learning_unit_type(group[0]["title"], group[0].get("category", "")),
            relationship="EXACT_DUPLICATE" if len(ids) > 1 else "KEEP_SEPARATE",
            summary=group[0].get("description", "")[:600],
            learning_objective=f"理解并能应用{group[0]['title'][:80]}。",
        ))
    return BucketCompileOutput(units=units)


async def compile_learning_candidates(
    candidates: list[dict],
    *,
    goal_name: str,
    goal_description: str,
    target_role: str,
    llm_service,
    batch_size: int = 6,
) -> tuple[list[dict], dict]:
    """Compile eligible points in bounded topic buckets with coverage validation."""
    eligible = []
    excluded = []
    counts = CounterLike()
    for candidate in candidates:
        status, reason = evaluate_learning_unit_eligibility(**{
            key: candidate.get(key, "")
            for key in ("name", "description", "category", "lesson_title", "course_name", "source_evidence")
        })
        if status != "LEARNABLE":
            counts[status] += 1
            excluded.append({"knowledge_point_id": candidate["id"], "status": status, "reason": reason})
            continue
        eligible.append({
            **candidate,
            "title": candidate["name"],
            "source_knowledge_point_ids": [candidate["id"]],
            "bucket": learning_topic_bucket(
                candidate["name"], category=candidate.get("category", ""),
                concept_names=candidate.get("concept_names", []),
            ),
        })

    clusters, exact_duplicate_count = _exact_candidate_clusters(eligible)
    bucketed: dict[str, list[dict]] = defaultdict(list)
    for item in clusters:
        bucketed[item["bucket"]].append(item)

    api_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    failed_buckets: list[str] = []
    planned: list[dict] = []
    all_point_ids = {candidate["id"] for candidate in eligible}

    def count_call() -> None:
        nonlocal api_calls
        api_calls += 1

    def count_usage(prompt: int, completion: int) -> None:
        nonlocal prompt_tokens, completion_tokens
        prompt_tokens += prompt
        completion_tokens += completion

    system = (
        "你是学习目标编译器，只处理当前主题桶，不得创造或遗漏候选ID。\n"
        "先判定 EXACT_DUPLICATE（核心内容重复）、MERGE_COMPLEMENTARY（同一学习目标的定义/例子/trade-off互补）、"
        "DEPTH_VARIANT（同主题但不同学习深度，必须分别保留并建立前置关系）、KEEP_SEPARATE（主题不同）。\n"
        "禁止仅因共享RAG、Agent、Transformer等词就合并；RAG基础、RAG工程、RAG评估、RAG选型要区分。"
        "项目/案例/方案不能并入概念单元。标题要短、清晰、适合学习；summary只能整合候选摘要，不得编造源课程正文。\n"
        "每个候选ID必须且只能出现在一个unit中。prerequisite_candidate_ids必须引用本桶候选ID，指向真正的先修项。"
        "unit_type只允许CONCEPT、METHOD、PRODUCT_SKILL、PROJECT_CASE、EVALUATION、TOOL。"
    )

    for bucket_name in sorted(bucketed):
        bucket_items = bucketed[bucket_name]
        if len(bucket_items) == 1:
            # A lone canonical candidate has nothing to compare or merge.
            unit = _fallback_bucket(bucket_items).units[0]
            point_ids = bucket_items[0]["source_knowledge_point_ids"]
            planned.append({
                "canonical_title": unit.canonical_title,
                "unit_type": unit.unit_type,
                "relationship": "EXACT_DUPLICATE" if len(point_ids) > 1 else "KEEP_SEPARATE",
                "summary": unit.summary,
                "learning_objective": unit.learning_objective,
                "source_knowledge_point_ids": point_ids,
                "prerequisite_knowledge_point_ids": [],
                "canonical_topic_id": bucket_name,
            })
            continue
        chunks = [bucket_items[index:index + batch_size] for index in range(0, len(bucket_items), batch_size)]
        bucket_plans: list[CanonicalUnitPlan] = []
        for chunk in chunks:
            allowed_ids = {item["id"] for item in chunk}
            payload = {
                "goal": {"name": goal_name, "description": goal_description, "target_role": target_role},
                "topic_bucket": bucket_name,
                "candidates": [{
                    "id": item["id"], "source_knowledge_point_ids": item["source_knowledge_point_ids"],
                    "title": item["title"][:180], "description": item.get("description", "")[:240],
                    "category": item.get("category", ""), "difficulty": item.get("difficulty", ""),
                    "prerequisite": item.get("prerequisite", "")[:140],
                    "course": item.get("course_name", ""), "section": item.get("section_title", ""),
                } for item in chunk],
            }
            used_fallback = False

            def fallback_for_chunk(batch=chunk) -> BucketCompileOutput:
                nonlocal used_fallback
                used_fallback = True
                return _fallback_bucket(batch)

            try:
                output = await llm_service.complete_structured(
                    BucketCompileOutput, system, json.dumps(payload, ensure_ascii=False),
                    fallback=fallback_for_chunk, retries=0, max_tokens=4000,
                    on_api_call=count_call, on_usage=count_usage,
                    on_fallback=lambda name=bucket_name: failed_buckets.append(name),
                )
                seen_ids = [candidate_id for unit in output.units for candidate_id in unit.candidate_ids]
                if set(seen_ids) != allowed_ids or len(seen_ids) != len(set(seen_ids)):
                    output = fallback_for_chunk()
                    if not used_fallback:
                        failed_buckets.append(bucket_name)
            except (RuntimeError, ValueError, TypeError, KeyError):
                output = fallback_for_chunk()
                failed_buckets.append(bucket_name)
            bucket_plans.extend(output.units)

        # Large buckets are first compiled in small calls, then reconciled using
        # short canonical summaries rather than retransmitting long source text.
        if len(chunks) > 1 and batch_size < len(bucket_plans) <= 8:
            recon_items = []
            for index, unit in enumerate(bucket_plans):
                all_ids = [candidate_id for candidate_id in unit.candidate_ids]
                recon_items.append({
                    "id": min(all_ids), "source_candidate_ids": all_ids,
                    "title": unit.canonical_title, "description": unit.summary[:180],
                    "category": unit.unit_type, "bucket": bucket_name,
                })
            recon_payload = {
                "goal": {"name": goal_name, "description": goal_description, "target_role": target_role},
                "topic_bucket": bucket_name,
                "candidates": recon_items,
            }
            recon_used_fallback = False

            def fallback_reconcile(items=recon_items) -> BucketCompileOutput:
                nonlocal recon_used_fallback
                recon_used_fallback = True
                return _fallback_bucket(items)

            try:
                reconciled = await llm_service.complete_structured(
                    BucketCompileOutput, system, json.dumps(recon_payload, ensure_ascii=False),
                    fallback=fallback_reconcile, retries=0, max_tokens=4000,
                    on_api_call=count_call, on_usage=count_usage,
                    on_fallback=lambda name=bucket_name: failed_buckets.append(name),
                )
                expected = {item["id"] for item in recon_items}
                seen = [candidate_id for unit in reconciled.units for candidate_id in unit.candidate_ids]
                if set(seen) != expected or len(seen) != len(set(seen)):
                    reconciled = fallback_reconcile()
                    if not recon_used_fallback:
                        failed_buckets.append(bucket_name)
                previous = {unit_id: unit for unit in bucket_plans for unit_id in unit.candidate_ids}
                bucket_plans = []
                for grouped_unit in reconciled.units:
                    source_units = [previous[unit_id] for unit_id in grouped_unit.candidate_ids if unit_id in previous]
                    representative_ids = list(dict.fromkeys(
                        point_id for unit in source_units for point_id in unit.candidate_ids
                    ))
                    bucket_plans.append(grouped_unit.model_copy(update={"candidate_ids": representative_ids}))
            except (RuntimeError, ValueError, TypeError, KeyError):
                failed_buckets.append(bucket_name)

        cluster_by_rep = {cluster["id"]: cluster for cluster in clusters}
        for unit in bucket_plans:
            point_ids = [
                point_id
                for candidate_id in unit.candidate_ids
                for point_id in cluster_by_rep.get(candidate_id, {"source_knowledge_point_ids": [candidate_id]})["source_knowledge_point_ids"]
            ]
            planned.append({
                "canonical_title": unit.canonical_title,
                "unit_type": unit.unit_type,
                "relationship": (
                    "EXACT_DUPLICATE"
                    if len(unit.candidate_ids) == 1 and len(point_ids) > 1
                    else unit.relationship
                ),
                "summary": unit.summary,
                "learning_objective": unit.learning_objective,
                "source_knowledge_point_ids": sorted(set(point_ids)),
                "prerequisite_knowledge_point_ids": list(dict.fromkeys(unit.prerequisite_candidate_ids)),
                "canonical_topic_id": bucket_name,
            })

    # Reconciliation outputs above may already contain raw point IDs. Normalize
    # every relation back to source knowledge-point references and enforce coverage.
    cluster_by_rep = {cluster["id"]: cluster for cluster in clusters}
    for unit in planned:
        expanded = []
        for candidate_id in unit["source_knowledge_point_ids"]:
            cluster = cluster_by_rep.get(candidate_id)
            expanded.extend(cluster["source_knowledge_point_ids"] if cluster else [candidate_id])
        unit["source_knowledge_point_ids"] = sorted(set(expanded) & all_point_ids)
        unit["prerequisite_knowledge_point_ids"] = [
            point_id for candidate_id in unit["prerequisite_knowledge_point_ids"]
            for point_id in (cluster_by_rep.get(candidate_id, {"source_knowledge_point_ids": [candidate_id]})["source_knowledge_point_ids"])
            if point_id in all_point_ids
        ]

    covered = [point_id for unit in planned for point_id in unit["source_knowledge_point_ids"]]
    if set(covered) != all_point_ids or len(covered) != len(set(covered)):
        # Never silently append omissions as arbitrary units; fail the compile so
        # the caller can roll back the entire transaction and retain the old path.
        raise ValueError("编译器未能完整且唯一覆盖所有可学习知识点；原学习路径保持不变。")

    relation_counts = CounterLike()
    for unit in planned:
        relation_counts[unit["relationship"]] += 1
    report = {
        "raw_candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "container_filtered_count": counts["SECTION_CONTAINER"] + counts["COURSE_CONTAINER"],
        "fragment_filtered_count": counts["FRAGMENT"],
        "noise_filtered_count": counts["NOISE"] + counts["EVIDENCE_ONLY"],
        "normalized_topic_count": len(clusters),
        "exact_duplicate_count": exact_duplicate_count,
        "merged_count": sum(unit["relationship"] == "MERGE_COMPLEMENTARY" for unit in planned),
        "depth_variant_count": relation_counts["DEPTH_VARIANT"],
        "kept_separate_count": sum(unit["relationship"] == "KEEP_SEPARATE" for unit in planned),
        "final_unit_count": len(planned),
        "api_calls": api_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "failed_buckets": sorted(set(failed_buckets)),
        "filtered_candidates": excluded,
    }
    return planned, report


class CounterLike(dict):
    def __missing__(self, key):
        return 0
