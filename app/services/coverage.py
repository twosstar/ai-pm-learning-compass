from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.models import Concept, KnowledgePoint, QuestionCapabilityMap, QuestionSupplementCache
from app.services.llm import llm_service


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, json.JSONDecodeError):
        return default


CAPABILITY_RULES = {
    "长尾知识": ("长尾", "冷门", "细节", "事实", "过期"),
    "LLM生成机制": ("生成", "幻觉", "模型", "推理", "参数"),
    "参数知识 vs Context": ("参数知识", "context", "上下文", "记忆"),
    "RAG工作机制": ("rag", "检索", "召回", "引用", "知识库"),
    "RAG vs Retraining trade-off": ("微调", "训练", "重训", "成本", "更新"),
    "Prompt约束": ("prompt", "提示词", "格式", "约束"),
    "工具调用与权限": ("工具", "tool", "权限", "调用", "执行"),
    "评估与兜底": ("评估", "验收", "指标", "兜底", "人工", "风险"),
}


def _capabilities(text: str) -> list[str]:
    value = (text or "").casefold()
    found = [name for name, terms in CAPABILITY_RULES.items() if any(term.casefold() in value for term in terms)]
    return found


def _required(question: str, point: KnowledgePoint) -> list[str]:
    text = " ".join((question or "", point.name or "", point.description or "")).casefold()
    required = []
    if any(term in text for term in ("作文批改", "作文评分", "ai作文", "写作批改", "自动批改")):
        required.extend([
            "产品目标与成功标准", "AI评估与学习效果", "算法工程可行性", "教育场景风险与人工兜底",
        ])
    if any(term in text for term in ("rag", "检索", "长尾", "知识")):
        required.extend(["长尾知识", "LLM生成机制", "参数知识 vs Context", "RAG工作机制", "RAG vs Retraining trade-off"])
    if any(term in text for term in ("agent", "智能体", "工具", "规划")):
        required.extend(["任务拆解", "工具调用与权限", "状态与迭代", "评估与兜底"])
    required.extend(_capabilities(text))
    return list(dict.fromkeys(required)) or ["概念理解", "机制解释", "场景迁移"]


def _covered(point: KnowledgePoint) -> list[str]:
    text = " ".join(
        [point.name or "", point.description or "", point.core_explanation or "", point.why_explanation or "", point.teaching_example or "", point.ai_pm_relevance or ""]
    )
    covered = _capabilities(text)
    # A course card explicitly contains these fields, but this is not evidence
    # that it covers every capability required by a question.
    if len(text) >= 80:
        covered.append("概念理解")
    if any(term in text for term in ("机制", "通过", "因为", "导致")):
        covered.append("机制解释")
    if any(term in text for term in ("例如", "场景", "用户", "案例")):
        covered.append("场景迁移")
    domain_coverage = {
        "产品目标与成功标准": ("产品目标", "成功标准", "业务目标"),
        "AI评估与学习效果": ("评估指标", "评分一致性", "学习效果", "误判率"),
        "算法工程可行性": ("算法", "标注数据", "模型能力", "工程可行", "时延"),
        "教育场景风险与人工兜底": ("人工复核", "教育场景风险", "学生安全", "教师复核"),
    }
    negations = ("不包含", "未涉及", "没有", "缺少", "不具备", "尚未", "缺乏", "未覆盖")
    def positively_present(signal: str) -> bool:
        start = 0
        while True:
            index = text.find(signal, start)
            if index < 0:
                return False
            prefix = text[max(0, index - 10):index]
            if not any(negation in prefix for negation in negations):
                return True
            start = index + len(signal)

    covered.extend(
        capability for capability, signals in domain_coverage.items()
        if any(positively_present(signal) for signal in signals)
    )
    return list(dict.fromkeys(covered))


class SupplementDraft(BaseModel):
    capability_name: str
    concept_and_method: str
    why_needed: str
    how_to_apply: str
    business_example: str
    transfer_prompt: str


class SupplementBatch(BaseModel):
    items: list[SupplementDraft]


SUPPLEMENT_VERSION = "question_supplement_v1"
_PLACEHOLDER_TERMS = (
    "UNAVAILABLE", "PLACEHOLDER", "尚未在本地 Concept Hub", "先补齐定义",
    "暂时没有内容", "待完善后提供", "当前题目不需要额外补充",
)


def _question_digest(question: str) -> str:
    normalized = " ".join((question or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_capability_gap(
    question: str, knowledge_point: KnowledgePoint, missing_capability: str
) -> dict:
    """Turn an abstract coverage label into a question-specific learning need."""
    context = " ".join((question, knowledge_point.name or "", knowledge_point.description or ""))
    if any(term in context for term in ("作文批改", "作文评分", "AI作文", "写作批改", "自动批改")):
        return {
            "topic": "K12 AI 作文自动批改产品目标与质量评估",
            "learning_need": (
                "围绕这道 K12 AI 作文自动批改题，把‘批改质量好’拆成可验证的产品目标："
                "评分与教师 rubric 的一致性、不同年级和题型的稳定性，以及学生采纳反馈后的写作提升；"
                "再用分层样本和线上护栏验证效果，并与算法、工程确认标注数据、模型能力、时延、隐私和人工复核的可行边界。"
            ),
            "concept_queries": ["AI 产品评估", "教育 AI 评估", "评估指标", "Evaluation Dataset", "Rubric"],
            "required_signal_groups": [
                ["目标", "成功标准"],
                ["指标", "一致性", "准确率", "学习效果", "误判率"],
                ["算法"], ["工程"],
                ["作文", "学生", "教师", "年级"],
            ],
        }

    point_name = knowledge_point.name or "当前知识点"
    question_focus = re.sub(r"\s+", " ", question).strip()[:180]
    if missing_capability == "机制解释":
        need = (
            f"针对教练题‘{question_focus}’，补足 {point_name} 的机制解释：说明输入与前置条件、"
            "关键处理步骤、每一步如何影响输出，以及用什么证据或指标判断机制有效；同时指出失效边界和兜底方式。"
        )
        queries = [point_name, "因果机制", "评估指标"]
    elif missing_capability == "场景迁移":
        need = (
            f"针对教练题‘{question_focus}’，把 {point_name} 迁移到真实产品流程：识别用户与业务目标、"
            "说明何时适用、需要哪些输入、如何观测结果，并明确风险和人工兜底。"
        )
        queries = [point_name, "产品场景", "业务流程"]
    elif missing_capability == "概念理解":
        need = (
            f"针对教练题‘{question_focus}’，建立 {point_name} 的准确心智模型：界定概念、输入输出、"
            "与相邻方案的区别及适用边界，并能用题目里的业务目标判断是否应该采用。"
        )
        queries = [point_name]
    else:
        need = (
            f"针对教练题‘{question_focus}’，补足‘{missing_capability}’对应的具体知识："
            f"解释它在 {point_name} 中承担的作用、决策依据、验证信号和失败兜底，避免只背术语。"
        )
        queries = [missing_capability, point_name]
    return {"topic": point_name, "learning_need": need, "concept_queries": queries, "required_signal_groups": []}


def _cjk_count(text: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in text)


def _normalize_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def _source_text(point: KnowledgePoint) -> str:
    evidence = _load(point.source_evidence_json, [])
    return " ".join(str(item.get("source_text") or "") for item in evidence if isinstance(item, dict))


def _quality_gate(
    draft: SupplementDraft, need: dict, question: str, point: KnowledgePoint
) -> tuple[bool, str]:
    fields = [
        draft.concept_and_method, draft.why_needed, draft.how_to_apply,
        draft.business_example, draft.transfer_prompt,
    ]
    content = "\n".join(fields)
    normalized = content.casefold()
    if any(term.casefold() in normalized for term in _PLACEHOLDER_TERMS):
        return False, "内容包含占位或内部状态文字"
    if any(len(value.strip()) < 12 for value in fields):
        return False, "概念、题目关联、使用方法、例子或迁移提示不完整"
    count = _cjk_count(content)
    if not 150 <= count <= 300:
        return False, f"正文中文长度为 {count} 字，要求 150–300 字"
    if not any(term in draft.how_to_apply for term in ("因为", "导致", "先", "再", "通过", "根据", "如果", "指标", "目标")):
        return False, "没有说明可执行的方法、因果或决策依据"
    if any(term in content for term in ("标准答案", "参考答案", "直接回答本题", "照着回答即可")):
        return False, "内容泄露了教练题答案"
    question_text = _normalize_text(question)
    body_text = _normalize_text(content)
    if len(question_text) >= 30 and question_text in body_text:
        return False, "补充正文复述了整道教练题"
    source = _normalize_text(_source_text(point))
    body = _normalize_text(content)
    if len(body) >= 70 and (body in source or SequenceMatcher(None, body, source).ratio() >= 0.72):
        return False, "补充内容与课程证据高度重复"
    for group in need.get("required_signal_groups", []):
        if not any(token in content for token in group):
            return False, f"缺少当前题目要求的具体要点：{'/'.join(group)}"
    name_parts = [part for part in re.split(r"[、，：/（）() ]+", point.name or "") if len(part) >= 2]
    compact_name = _normalize_text(point.name or "")
    name_parts.extend(compact_name[index:index + 2] for index in range(max(0, len(compact_name) - 1)))
    if point.name and not any(term in _normalize_text(content) for term in name_parts if len(term) >= 2):
        return False, "内容未锚定当前知识点"
    return True, ""


def _find_local_concept(db: Session, need: dict) -> Concept | None:
    cards = db.scalars(select(Concept).where(Concept.card_status == "READY")).all()
    queries = [_normalize_text(q) for q in need.get("concept_queries", []) if q]
    ranked: list[tuple[int, Concept]] = []
    for card in cards:
        names = [card.canonical_name, card.display_name, *_load(card.aliases_json, [])]
        normalized_names = [_normalize_text(name) for name in names]
        score = sum(1 for query in queries if any(query == name or query in name or name in query for name in normalized_names if name))
        if score:
            ranked.append((score, card))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _local_draft(capability_name: str, need: dict, card: Concept, question: str) -> SupplementDraft:
    if "作文自动批改" in need.get("topic", ""):
        method = (
            "先按年级和题型分层，再对照教师rubric检查评分一致性与学习效果；"
            "算法确认标注和模型边界，工程确认时延、隐私及人工复核，最后看误判率。"
        )
    else:
        method = (
            f"先明确{need['topic']}在题目场景中的输入、目标和限制，"
            f"再按{card.display_name}的方法处理；{card.core_mechanism or card.when_to_use}，"
            "最后用可观察的结果判断是否适用。"
        )[:105]
    return SupplementDraft(
        capability_name=capability_name,
        concept_and_method=(
            f"{card.display_name}：{card.short_definition or card.core_mechanism}"
        )[:85],
        why_needed=(
            f"本题‘{question[:32]}’需要判断{need['topic']}的适用边界；"
            f"{card.ai_pm_relevance or card.when_to_use}"
        )[:75],
        how_to_apply=method,
        business_example=(card.example or card.when_to_use)[:65],
        transfer_prompt=f"迁移思考：若本题的用户、数据质量或风险阈值变化，{card.display_name} 的使用条件和验证指标要如何调整？",
    )


def _draft_payload(draft: SupplementDraft) -> dict:
    return draft.model_dump()


class CoverageService:
    version = "coverage_v2"

    async def prepare(
        self, db: Session, point: KnowledgePoint, question: str, *, retry_failed: bool = False
    ) -> dict:
        question = " ".join((question or "").split())
        if not question:
            raise ValueError("需要真实教练问题才能分析能力缺口。")
        digest = _question_digest(question)
        required = _required(question, point)
        covered = _covered(point)
        missing = [item for item in required if item not in covered]
        point.required_capabilities_json = _dump(required)
        point.covered_capabilities_json = _dump(covered)
        point.coverage_gap_json = _dump(missing)
        point.mechanism_chain_json = _dump(["问题信号", "机制选择", "输入与处理", "输出与指标", "风险与兜底"])
        point.trigger_signals_json = _dump(["看到长尾或最新知识需求时想到 RAG", "看到模型能力不足时区分参数知识与 Context", "看到方案选择题时比较成本、更新速度和风险"] if "RAG" in " ".join(required) else ["识别题目中的输入、机制、输出和风险"])
        point.tradeoff_compare_json = _dump([{"options": ["RAG", "继续训练"], "dimensions": ["适用问题", "成本", "更新速度", "是否改变模型参数"]}]) if "RAG vs Retraining trade-off" in required else _dump([])
        point.application_bridge_json = _dump({
            "status": "NEEDS_SUPPLEMENT" if missing else "READY",
            "bridge_required": False,
            "question_digest": digest,
            "levels": [
                {"level": "A", "title": "问题识别", "prompt": "指出题目中的异常信号，并判断是知识、机制、权衡还是表达问题。"},
                {"level": "B", "title": "机制选择", "prompt": "从已学机制和系统补充中选择方案，并说明为什么适用。"},
                {"level": "C", "title": "因果链填空", "prompt": "补齐问题 → 机制 → 结果 → 指标/兜底的因果链。"},
                {"level": "D", "title": "半开放回答", "prompt": "用自己的话完成一个具体业务场景判断。"},
            ],
            "progressive_hint": ["完整骨架", "部分节点", "只给问题信号", "不再提示"],
        })
        question_id = f"attempt:{point.id}:{digest}"
        mapping = db.get(QuestionCapabilityMap, question_id)
        if not mapping:
            mapping = QuestionCapabilityMap(question_id=question_id, knowledge_point_id=point.id)
            db.add(mapping)
        mapping.required_capabilities_json = _dump(required)
        mapping.covered_capabilities_json = _dump(covered)
        mapping.missing_capabilities_json = _dump(missing)
        mapping.coverage_version = self.version
        db.commit()

        stats = {"supplement_api_calls": 0, "supplement_cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}
        if not missing:
            return self.view(db, point, stats=stats)

        records: list[QuestionSupplementCache] = []
        pending: list[tuple[QuestionSupplementCache, dict]] = []
        for capability in missing:
            need = resolve_capability_gap(question, point, capability)
            record = db.scalar(select(QuestionSupplementCache).where(
                QuestionSupplementCache.knowledge_point_id == point.id,
                QuestionSupplementCache.question_digest == digest,
                QuestionSupplementCache.capability_name == capability,
                QuestionSupplementCache.version == SUPPLEMENT_VERSION,
            ))
            if record and record.status == "READY":
                valid, reason = self._stored_content_is_ready(record, need, question, point)
                if valid:
                    stats["supplement_cache_hits"] += 1
                    records.append(record)
                    continue
                record.status = "FAILED"
                record.failure_reason = reason
            if record and record.status == "FAILED" and not retry_failed:
                record.learning_need = need["learning_need"]
                records.append(record)
                continue
            if not record:
                record = QuestionSupplementCache(
                    knowledge_point_id=point.id,
                    question_digest=digest,
                    capability_name=capability,
                    learning_need=need["learning_need"],
                    status="GENERATING",
                    version=SUPPLEMENT_VERSION,
                )
                db.add(record)
                db.flush()
            record.learning_need = need["learning_need"]
            record.status = "GENERATING"
            record.failure_reason = ""
            record.content_json = "{}"
            record.generation_attempts = (record.generation_attempts or 0) + 1
            records.append(record)

            concept = _find_local_concept(db, need)
            if concept:
                local = _local_draft(capability, need, concept, question)
                valid, reason = _quality_gate(local, need, question, point)
                if valid:
                    record.status = "READY"
                    record.source_type = "LOCAL_CONCEPT"
                    record.concept_id = concept.id
                    record.content_json = _dump(_draft_payload(local))
                    record.failure_reason = ""
                    continue
            pending.append((record, need))

        db.commit()
        if pending and not getattr(llm_service, "_configured", True):
            for record, _ in pending:
                record.status = "FAILED"
                record.source_type = ""
                record.failure_reason = "未配置模型 API，无法生成题目专属补充。"
            db.commit()
            return self.view(db, point, stats=stats)

        # One request can create every outstanding item for this question. Retry
        # only quality failures, at most once, to keep token use predictable.
        for _ in range(2):
            if not pending:
                break
            expected = {record.capability_name: (record, need) for record, need in pending}
            prompt_items = [
                {"capability_name": name, "learning_need": need["learning_need"], "topic": need["topic"]}
                for name, (_, need) in expected.items()
            ]

            def count_call() -> None:
                stats["supplement_api_calls"] += 1

            def count_usage(prompt_tokens: int, completion_tokens: int) -> None:
                stats["prompt_tokens"] += prompt_tokens
                stats["completion_tokens"] += completion_tokens

            try:
                generated = await llm_service.complete_structured(
                    SupplementBatch,
                    "你是 AI 产品经理学习教练。只讲解指定的学习缺口，不要回答或代写正式教练题。"
                    "每项必须结合题目和知识点，分别说明概念/方法、为什么需要、怎么使用、具体业务例子、迁移思考。"
                    "五字段中文正文合计 150–300 字；避免泛泛定义、占位符、内部状态和课程原文复述。",
                    _dump({
                        "coach_question": question,
                        "knowledge_point": {
                            "name": point.name,
                            "description": point.description,
                            "course_explanation": point.core_explanation,
                        },
                        "course_evidence_to_avoid_repeating": _source_text(point)[:1200],
                        "specific_learning_gaps": prompt_items,
                        "required_signal_groups": {
                            name: need["required_signal_groups"]
                            for name, (_, need) in expected.items()
                        },
                        "return_contract": "每个 capability_name 恰好返回一项；不要输出正式题答案。",
                    }),
                    fallback=lambda: SupplementBatch(items=[]),
                    retries=0,
                    max_tokens=1800,
                    on_api_call=count_call,
                    on_usage=count_usage,
                )
            except Exception:
                generated = SupplementBatch(items=[])

            generated_by_name = {item.capability_name: item for item in generated.items}
            still_pending: list[tuple[QuestionSupplementCache, dict]] = []
            for capability, (record, need) in expected.items():
                draft = generated_by_name.get(capability)
                if draft:
                    valid, reason = _quality_gate(draft, need, question, point)
                else:
                    valid, reason = False, "模型没有为该缺口返回有效正文"
                if valid:
                    record.status = "READY"
                    record.source_type = "AI_GENERATED"
                    record.concept_id = None
                    record.content_json = _dump(_draft_payload(draft))
                    record.failure_reason = ""
                else:
                    record.status = "GENERATING"
                    record.failure_reason = reason
                    still_pending.append((record, need))
            db.commit()
            pending = still_pending

        for record, _ in pending:
            record.status = "FAILED"
            record.source_type = ""
            if not record.failure_reason:
                record.failure_reason = "补充内容未通过质量检查。"
        db.commit()
        return self.view(db, point, stats=stats)

    @staticmethod
    def _stored_content_is_ready(record: QuestionSupplementCache, need: dict, question: str, point: KnowledgePoint) -> tuple[bool, str]:
        try:
            draft = SupplementDraft.model_validate(_load(record.content_json, {}))
        except Exception:
            return False, "缓存内容结构无效"
        return _quality_gate(draft, need, question, point)

    def view(self, db: Session, point: KnowledgePoint, *, stats: dict | None = None) -> dict:
        bridge = _load(point.application_bridge_json, {})
        digest = bridge.get("question_digest")
        missing = _load(point.coverage_gap_json, [])
        supplements = db.scalars(select(QuestionSupplementCache).where(
            QuestionSupplementCache.knowledge_point_id == point.id,
            QuestionSupplementCache.question_digest == digest,
            QuestionSupplementCache.version == SUPPLEMENT_VERSION,
        ).order_by(QuestionSupplementCache.id.asc())).all() if digest and missing else []
        serialized = []
        for record in supplements:
            item = {
                "capability_name": record.capability_name,
                "learning_need": record.learning_need,
                "status": record.status,
                "source_type": record.source_type,
                "concept_id": record.concept_id,
                "failure_reason": record.failure_reason,
                "generation_attempts": record.generation_attempts,
            }
            if record.status == "READY":
                item.update(_load(record.content_json, {}))
            serialized.append(item)
        ready_count = sum(item["status"] == "READY" for item in serialized)
        failed_count = sum(item["status"] == "FAILED" for item in serialized)
        generating_count = sum(item["status"] == "GENERATING" for item in serialized)
        if not missing:
            supplement_status = "NOT_NEEDED"
        elif generating_count:
            supplement_status = "GENERATING"
        elif failed_count:
            supplement_status = "FAILED"
        elif ready_count == len(missing):
            supplement_status = "READY"
        else:
            supplement_status = "FAILED"
        return {
            "required_capabilities": _load(point.required_capabilities_json, []),
            "covered_capabilities": _load(point.covered_capabilities_json, []),
            "coverage_gap": missing,
            "source_evidence": _load(point.source_evidence_json, []),
            "mechanism_chain": _load(point.mechanism_chain_json, []),
            "trigger_signals": _load(point.trigger_signals_json, []),
            "tradeoff_compare": _load(point.tradeoff_compare_json, []),
            "application_bridge": bridge,
            "supplements": serialized,
            "supplement_status": supplement_status,
            "supplemented_count": ready_count,
            "supplement_failed_count": failed_count,
            "supplement_cache_hits": (stats or {}).get("supplement_cache_hits", 0),
            "supplement_api_calls": (stats or {}).get("supplement_api_calls", 0),
            "supplement_prompt_tokens": (stats or {}).get("prompt_tokens", 0),
            "supplement_completion_tokens": (stats or {}).get("completion_tokens", 0),
        }


coverage_service = CoverageService()
