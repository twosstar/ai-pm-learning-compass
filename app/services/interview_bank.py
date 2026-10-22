import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    InterviewImportBatch,
    InterviewQuestion,
    KnowledgePoint,
    Weakness,
)
from app.schemas.interview_bank import ImportPreviewRequest, InterviewQuestionDraft
from app.schemas.learning import GeneratedQuestion

NUMBERING = re.compile(
    r"^\s*(?:(?:问题|question|q)\s*\d{1,3}\s*[:：.、]|第?\d{1,3}\s*[.、:：)）]|[-*•])\s*",
    re.IGNORECASE,
)
EXPLICIT_QUESTION_LABEL = re.compile(
    r"^\s*(?:问题|question|q)\s*\d{1,3}\s*[:：.、]",
    re.IGNORECASE,
)
QUESTION_START = re.compile(
    r"^(?:请|如何|为什么|什么|哪些|是否|怎么|怎样|谈谈|说说|介绍|设计|假设|如果|你会|你如何|"
    r"what|why|how|design|describe|tell\s+me)",
    re.IGNORECASE,
)

TOPIC_RULES = [
    (("rag", "检索增强", "向量库", "召回", "rerank", "重排"), "RAG"),
    (("agent", "智能体", "memory", "tool calling", "规划"), "Agent"),
    (("大模型", "llm", "prompt", "提示词", "fine-tun", "微调"), "LLM应用"),
    (("指标", "precision", "recall", "准确率", "召回率", "评估"), "模型评估"),
    (("需求", "用户研究", "痛点", "场景"), "需求分析"),
    (("商业化", "收入", "盈利", "定价", "付费"), "商业化"),
    (("竞品", "竞争", "市场"), "竞品与市场"),
    (("项目", "复盘", "失败", "冲突", "推进", "研发"), "项目深挖"),
    (("数据", "埋点", "ab测试", "a/b", "漏斗"), "数据分析"),
]


def normalize_question(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def question_hash(value: str) -> str:
    return hashlib.sha256(normalize_question(value).encode("utf-8")).hexdigest()


def clean_question(value: str) -> str:
    value = NUMBERING.sub("", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t-—")


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [part.strip() for part in re.split(r"[|；;\n]", str(value)) if part.strip()]


class InterviewBankService:
    max_questions = 100

    @staticmethod
    def _classification(question: str) -> tuple[str, str, str, int, list[str], list[str]]:
        lowered = question.casefold()
        topic = "产品通识"
        for keywords, label in TOPIC_RULES:
            if any(keyword in lowered for keyword in keywords):
                topic = label
                break
        if any(word in lowered for word in ("设计", "方案", "从0到1", "case")):
            question_type = "产品设计 / Case"
            framework = ["明确目标与用户", "拆解场景和需求", "设计方案", "指标与风险"]
        elif any(word in lowered for word in ("选择", "对比", "权衡", "trade-off", "还是")):
            question_type = "技术选型 / Trade-off"
            framework = ["先给结论", "说明适用条件", "比较效果、成本与风险", "给出验证方式"]
        elif any(word in lowered for word in ("复盘", "失败", "冲突", "推进", "定位问题")):
            question_type = "项目深挖 / Troubleshooting"
            framework = ["背景与目标", "个人职责", "关键判断和行动", "结果与复盘"]
        elif topic in {"RAG", "Agent", "LLM应用", "模型评估"}:
            question_type = "AI技术理解"
            framework = ["定义", "核心机制", "产品场景", "指标、风险或选型"]
        else:
            question_type = "产品通识"
            framework = ["结论", "依据", "案例", "结果或验证"]
        high_terms = ("架构", "系统设计", "故障", "商业战略", "复杂", "高并发")
        medium_terms = ("权衡", "指标", "落地", "复盘", "选型", "评估")
        difficulty = (
            "高阶"
            if any(item in lowered for item in high_terms)
            else "进阶"
            if any(item in lowered for item in medium_terms)
            else "基础"
        )
        value = 5 if topic in {"RAG", "Agent", "LLM应用", "模型评估"} else 4
        if topic == "产品通识" and question_type == "产品通识":
            value = 3
        must_have = framework[:3]
        tags = [topic, question_type]
        return question_type, topic, difficulty, value, must_have, tags

    @staticmethod
    def _structured_rows(raw_text: str) -> list[dict] | None:
        stripped = raw_text.strip()
        if stripped.startswith("["):
            try:
                payload = json.loads(stripped)
                if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
                    return payload
            except json.JSONDecodeError:
                pass
        first_line = stripped.splitlines()[0] if stripped else ""
        if "," in first_line and "question" in first_line.casefold():
            try:
                return list(csv.DictReader(io.StringIO(stripped)))
            except csv.Error:
                pass
        return None

    @classmethod
    def _extract_question_texts(cls, raw_text: str) -> list[str]:
        rows = cls._structured_rows(raw_text)
        if rows is not None:
            return [clean_question(str(item.get("question", ""))) for item in rows]
        lines = [line.strip() for line in raw_text.replace("\r", "\n").split("\n")]
        result = []
        context_lines: list[str] = []

        def flush_context() -> None:
            if context_lines:
                merged = clean_question(" ".join(context_lines))
                if len(merged) >= 4:
                    result.append(merged)
                context_lines.clear()

        for line in lines:
            if not line:
                continue
            cleaned = clean_question(line)
            if len(cleaned) < 4:
                continue
            is_question = cleaned.endswith(("?", "？")) or bool(QUESTION_START.match(cleaned))
            if EXPLICIT_QUESTION_LABEL.match(line):
                # “问题N：” is an unambiguous question boundary, unlike a
                # generic ordered list that often enumerates one scenario's
                # background and constraints.
                flush_context()
                result.append(cleaned)
            elif NUMBERING.match(line):
                if is_question:
                    if context_lines:
                        context_lines.append(cleaned)
                        flush_context()
                    else:
                        result.append(cleaned)
                else:
                    context_lines.append(cleaned)
            elif context_lines:
                context_lines.append(cleaned)
            elif is_question:
                result.append(cleaned)
        flush_context()
        return result[: cls.max_questions]

    @classmethod
    def _drafts(cls, payload: ImportPreviewRequest) -> list[InterviewQuestionDraft]:
        structured = cls._structured_rows(payload.raw_text)
        if structured is not None:
            raw_items = structured[: cls.max_questions]
        else:
            raw_items = [{"question": text} for text in cls._extract_question_texts(payload.raw_text)]
        drafts = []
        for item in raw_items:
            question = clean_question(str(item.get("question", "")))
            if len(question) < 4:
                continue
            question_type, topic, difficulty, value, must_have, tags = cls._classification(question)
            drafts.append(
                InterviewQuestionDraft(
                    question=question,
                    source=str(item.get("source") or payload.source_name),
                    company=str(item.get("company") or payload.default_company),
                    role=str(item.get("role") or payload.default_role),
                    question_type=str(item.get("question_type") or question_type),
                    topic=str(item.get("topic") or topic),
                    difficulty=str(item.get("difficulty") or difficulty),
                    interview_value=int(item.get("interview_value") or value),
                    must_have_points=_string_list(item.get("must_have_points")) or must_have,
                    follow_ups=_string_list(item.get("follow_ups")),
                    answer_framework=_string_list(item.get("answer_framework"))
                    or [*must_have, "总结"],
                    reference_answer=str(item.get("reference_answer") or ""),
                    tags=_string_list(item.get("tags")) or tags,
                )
            )
        return drafts

    def preview(self, db: Session, payload: ImportPreviewRequest) -> tuple[InterviewImportBatch, list]:
        drafts = self._drafts(payload)
        if not drafts:
            raise ValueError("没有识别到题目。请让每道题单独一行，并保留问号或数字编号。")
        existing_hashes = set(
            db.scalars(
                select(InterviewQuestion.normalized_hash).where(InterviewQuestion.active.is_(True))
            ).all()
        )
        seen = set()
        duplicate_count = 0
        for draft in drafts:
            digest = question_hash(draft.question)
            if digest in existing_hashes:
                draft.duplicate = True
                draft.duplicate_reason = "题库中已存在"
            elif digest in seen:
                draft.duplicate = True
                draft.duplicate_reason = "本次导入内重复"
            if draft.duplicate:
                duplicate_count += 1
            seen.add(digest)
        batch = InterviewImportBatch(
            source_name=payload.source_name,
            source_locator=payload.source_locator,
            input_kind=payload.input_kind,
            content_hash=hashlib.sha256(payload.raw_text.encode("utf-8")).hexdigest(),
            candidate_count=len(drafts),
            duplicate_count=duplicate_count,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        return batch, drafts

    @staticmethod
    def _match_knowledge_point(db: Session, draft: InterviewQuestionDraft) -> int | None:
        points = list(db.scalars(select(KnowledgePoint)).all())
        haystack = normalize_question(f"{draft.topic} {draft.question} {' '.join(draft.tags)}")
        matches = [point for point in points if normalize_question(point.name) in haystack]
        if not matches:
            matches = [
                point
                for point in points
                if normalize_question(draft.topic) in normalize_question(
                    f"{point.name} {point.category}"
                )
            ]
        return max(matches, key=lambda point: len(normalize_question(point.name))).id if matches else None

    def commit(
        self, db: Session, batch_id: int, drafts: list[InterviewQuestionDraft]
    ) -> tuple[list[int], int]:
        batch = db.get(InterviewImportBatch, batch_id)
        if not batch:
            raise LookupError("导入批次不存在。")
        if batch.status != "preview":
            raise ValueError("这个批次已经确认或回滚，不能重复导入。")
        inserted_ids, duplicate_count = [], 0
        seen = set()
        for draft in drafts[: self.max_questions]:
            digest = question_hash(draft.question)
            exists = db.scalar(
                select(InterviewQuestion.id).where(InterviewQuestion.normalized_hash == digest)
            )
            if draft.duplicate or exists or digest in seen:
                duplicate_count += 1
                continue
            record = InterviewQuestion(
                import_batch_id=batch.id,
                knowledge_point_id=self._match_knowledge_point(db, draft),
                question=clean_question(draft.question),
                normalized_hash=digest,
                source=draft.source,
                company=draft.company,
                role=draft.role,
                question_type=draft.question_type,
                topic=draft.topic,
                difficulty=draft.difficulty,
                interview_value=draft.interview_value,
                must_have_points_json=json.dumps(draft.must_have_points, ensure_ascii=False),
                follow_ups_json=json.dumps(draft.follow_ups, ensure_ascii=False),
                answer_framework_json=json.dumps(draft.answer_framework, ensure_ascii=False),
                reference_answer=draft.reference_answer,
                tags_json=json.dumps(draft.tags, ensure_ascii=False),
            )
            db.add(record)
            db.flush()
            inserted_ids.append(record.id)
            seen.add(digest)
        batch.status = "committed"
        batch.inserted_count = len(inserted_ids)
        batch.duplicate_count = duplicate_count
        batch.committed_at = datetime.now(UTC)
        db.commit()
        return inserted_ids, duplicate_count

    @staticmethod
    def rollback(db: Session, batch_id: int) -> int:
        batch = db.get(InterviewImportBatch, batch_id)
        if not batch:
            raise LookupError("导入批次不存在。")
        if batch.status == "rolled_back":
            return 0
        removed = db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.import_batch_id == batch_id
            )
        ) or 0
        db.execute(delete(InterviewQuestion).where(InterviewQuestion.import_batch_id == batch_id))
        batch.status = "rolled_back"
        batch.rolled_back_at = datetime.now(UTC)
        db.commit()
        return removed

    @staticmethod
    def list_batches(db: Session) -> list[dict]:
        rows = db.scalars(
            select(InterviewImportBatch).order_by(InterviewImportBatch.id.desc()).limit(50)
        ).all()
        return [
            {
                "id": row.id,
                "source_name": row.source_name,
                "input_kind": row.input_kind,
                "source_type": row.source_type,
                "source_cursor": row.source_cursor,
                "scroll_count": row.scroll_count,
                "stop_reason": row.stop_reason,
                "status": row.status,
                "candidate_count": row.candidate_count,
                "inserted_count": row.inserted_count,
                "duplicate_count": row.duplicate_count,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    @staticmethod
    def _to_dict(record: InterviewQuestion) -> dict:
        return {
            "id": record.id,
            "import_batch_id": record.import_batch_id,
            "knowledge_point_id": record.knowledge_point_id,
            "question": record.question,
            "source": record.source,
            "company": record.company,
            "role": record.role,
            "question_type": record.question_type,
            "topic": record.topic,
            "difficulty": record.difficulty,
            "interview_value": record.interview_value,
            "must_have_points": json.loads(record.must_have_points_json or "[]"),
            "follow_ups": json.loads(record.follow_ups_json or "[]"),
            "answer_framework": json.loads(record.answer_framework_json or "[]"),
            "reference_answer": record.reference_answer,
            "tags": json.loads(record.tags_json or "[]"),
            "duplicate": False,
            "duplicate_reason": "",
            "times_used": record.times_used,
        }

    def list_questions(
        self, db: Session, topic: str = "", question_type: str = "", weakness_only: bool = False
    ) -> list[dict]:
        statement = select(InterviewQuestion).where(InterviewQuestion.active.is_(True))
        if topic:
            statement = statement.where(InterviewQuestion.topic == topic)
        if question_type:
            statement = statement.where(InterviewQuestion.question_type == question_type)
        if weakness_only:
            statement = (
                statement.join(
                    Weakness, Weakness.knowledge_point_id == InterviewQuestion.knowledge_point_id
                )
                .where(Weakness.resolved.is_(False))
                .distinct()
            )
        rows = db.scalars(
            statement.order_by(
                InterviewQuestion.interview_value.desc(), InterviewQuestion.id.desc()
            ).limit(200)
        ).all()
        return [self._to_dict(row) for row in rows]

    @staticmethod
    def _mark_used(db: Session, record: InterviewQuestion) -> None:
        record.times_used += 1
        record.last_used_at = datetime.now(UTC)
        db.commit()

    def select_for_mock(
        self, db: Session, focus: str = "", exclude_ids: set[int] | None = None
    ) -> InterviewQuestion | None:
        statement = select(InterviewQuestion).where(InterviewQuestion.active.is_(True))
        if exclude_ids:
            statement = statement.where(InterviewQuestion.id.not_in(exclude_ids))
        if focus and focus != "综合产品能力":
            pattern = f"%{focus}%"
            focused = db.scalar(
                statement.where(
                    or_(
                        InterviewQuestion.topic.ilike(pattern),
                        InterviewQuestion.question_type.ilike(pattern),
                        InterviewQuestion.tags_json.ilike(pattern),
                    )
                ).order_by(InterviewQuestion.times_used, InterviewQuestion.interview_value.desc())
            )
            if focused:
                self._mark_used(db, focused)
                return focused
        record = db.scalar(
            statement.order_by(
                InterviewQuestion.times_used, InterviewQuestion.interview_value.desc(),
                InterviewQuestion.id,
            )
        )
        if record:
            self._mark_used(db, record)
        return record

    @staticmethod
    def get_question(db: Session, question_id: int | None) -> InterviewQuestion | None:
        return db.get(InterviewQuestion, question_id) if question_id else None

    def select_for_learning(
        self, db: Session, point: KnowledgePoint, category: str
    ) -> GeneratedQuestion | None:
        pattern = f"%{point.name}%"
        record = db.scalar(
            select(InterviewQuestion)
            .where(
                InterviewQuestion.active.is_(True),
                or_(
                    InterviewQuestion.knowledge_point_id == point.id,
                    InterviewQuestion.question.ilike(pattern),
                    InterviewQuestion.topic.ilike(f"%{point.category}%"),
                    InterviewQuestion.tags_json.ilike(pattern),
                ),
            )
            .order_by(
                (InterviewQuestion.knowledge_point_id == point.id).desc(),
                InterviewQuestion.times_used,
                InterviewQuestion.interview_value.desc(),
            )
        )
        if not record:
            return None
        self._mark_used(db, record)
        learning_type = {
            "AI技术理解": "原理理解题",
            "技术选型 / Trade-off": "技术选型题",
            "产品设计 / Case": "场景Case题",
            "项目深挖 / Troubleshooting": "面试题",
            "产品通识": "面试题",
        }.get(record.question_type, "面试题")
        return GeneratedQuestion(
            question_type=learning_type,
            difficulty={"基础": 1, "进阶": 2, "高阶": 3}.get(record.difficulty, 1),
            question=record.question,
            assessment_focus=json.loads(record.tags_json or "[]") or [record.topic],
            interview_category=category,
            interview_value=record.interview_value,
            interview_depth="P1" if record.difficulty == "基础" else "P2",
            why_interviewer_asks=f"来源于真实面试题库：{record.source}",
            must_have_points=json.loads(record.must_have_points_json or "[]")[:8],
            bonus_points=[],
            unnecessary_detail="以题库必答点为准，不要求无关的算法推导或代码实现。",
        )


interview_bank_service = InterviewBankService()
