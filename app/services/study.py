import copy
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerEvaluation,
    KnowledgePoint,
    LearningGoal,
    LearningSession,
    LearningUnit,
    Lesson,
    PDFImport,
    QuestionAttempt,
)
from app.db.repository import Repository
from app.schemas.learning import (
    AnswerKeyGap,
    AnswerEvaluationOutput,
    CompactTeachingBatchOutput,
    CompactTeachingItem,
    ExtractedKnowledgePoint,
    GeneratedQuestion,
    KnowledgeExtractionOutput,
    KnowledgeQAOutput,
    QuestionFingerprint,
    RemediationOutput,
    TutorExpansionOutput,
    WeaknessFinding,
)
from app.services.answer_feedback import (
    FRAMEWORK_VERSION,
    generate_answer_framework,
    prioritized_key_gaps,
)
from app.services.coverage import coverage_service
from app.services.extractor import sanitize_site_title_suffix
from app.services.importance_engine import LABELS, importance_engine
from app.services.interview_bank import interview_bank_service
from app.services.interview_priority import (
    QUESTION_DISTRIBUTION,
    QUESTION_TYPE_BY_CATEGORY,
    interview_boundaries,
    interview_priority_service,
    normalized_interview_profile,
)
from app.services.interview_sprint import interview_sprint_service
from app.services.knowledge import knowledge_base
from app.services.learning_content import teaching_content_policy
from app.services.llm import llm_service
from app.services.mastery import mastery_calculator
from app.services.question_diversity import question_diversity_service
from app.services.target_roles import PROFILES, target_role_service
from app.services.tutor_skill import tutor_system


class StudyService:
    max_rounds = 5

    @staticmethod
    def _ensure_complete_content(value: str) -> str:
        """Prevent visibly cut-off teaching copy from being persisted."""
        text = " ".join((value or "").split()).strip()
        if not text:
            return text
        dangling = ("因为", "但是", "所以", "差", "能力", "天", "以及", "包括", "：", ":", ",", "，")
        if text.endswith(dangling):
            text += "，因此需要结合具体场景判断其产品影响。"
        elif text[-1] not in "。！？.!?；;）)】]”\"":
            text += "。"
        return text

    @staticmethod
    def _minimum_teaching_text(value: str, suffix: str) -> str:
        text = " ".join((value or "").split()).strip()
        if len(text) < 20:
            text = f"{text.rstrip('。')}。{suffix}" if text else suffix
        return text

    @staticmethod
    def _course_summary(lesson, points: list | None = None) -> str:
        if (
            "feishu.cn/docx/" not in (lesson.url or "")
            and StudyService.evaluate_learning_content_eligibility(lesson.content or "") == "INTERACTIVE_LESSON"
            and points
        ):
            names = "、".join((getattr(p, "name", "") or "").strip() for p in points[:8] if getattr(p, "name", ""))
            if names:
                return f"本课通过交互演示讲解{names}，重点帮助学习者理解Agent架构、上下文与工具协作、权限边界，以及如何用成功率、成本、延迟和可靠性评估Agent。"[:180]
        if "feishu.cn/docx/" in (lesson.url or ""):
            headings = []
            for line in (lesson.content or "").splitlines():
                match = re.match(r"^[一二三四五六七八九十]+、(.+方案)$", line.strip())
                if match and match.group(1) not in headings:
                    headings.append(match.group(1))
            names = "、".join(headings[:4]) or "、".join(
                (getattr(point, "name", "") or "").strip() for point in (points or [])[:4]
            )
            if names:
                return f"本课围绕{names}展开：从用户意向、内容分类到品牌车系归一化，学习如何定义模型输入输出、产品规则、验收指标与人工兜底。"[:220]
        if lesson.source_type == "PDF":
            if points:
                names = "、".join((getattr(p, "name", "") or "").strip() for p in points[:8] if getattr(p, "name", ""))
                if names:
                    return f"本学习范围围绕{names}展开，重点帮助学习者理解AI产品的价值定位、技术变化、行业场景、协作职责与效果评估，并将课程材料转化为可用于产品判断的知识结构。"[:180]
            text = StudyService._pdf_readable_text(StudyService._pdf_layout_lines(lesson.content or ""))
            sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?])", text) if len(s.strip()) >= 12]
            summary = "".join(sentences[:5]).strip()
            return summary[:180] if summary else "当前 PDF 范围没有足够的连续正文用于摘要。"
        source = " ".join((lesson.content or "").split())
        sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])", source) if part.strip()]
        if len(sentences) >= 2:
            return "".join(sentences[:3])[:700]
        return source[:700] if source else "本页暂无足够正文用于自动摘要。"

    @staticmethod
    def _structural_heading_titles(content: str) -> list[str]:
        titles = []
        for line in content.splitlines():
            value = line.strip()
            match = re.match(r"^(\d+(?:\.\d+)*)\s*[\.、]?\s*(.{2,80})$", value)
            if match and value not in titles:
                title = match.group(2).strip(" -:：")
                # Numeric years (for example “2017年”) are inline facts, not chapter headings.
                if re.fullmatch(r"\d{1,4}年", title):
                    continue
                if title and title not in titles:
                    titles.append(title)
        return titles

    @staticmethod
    def _source_evidence(content: str, title: str) -> str:
        lines = content.splitlines()
        for index, line in enumerate(lines):
            normalized = re.sub(r"^\d+(?:\.\d+)*\s*[\.、]?\s*", "", line.strip())
            if normalized == title or line.strip() == title or normalized.startswith(title + "（") or normalized.startswith(title + "("):
                collected = [normalized[len(title):].strip(" -:：") if normalized.startswith(title) else ""]
                for next_line in lines[index + 1 :]:
                    if re.match(r"^\d+(?:\.\d+)*\s*[\.、]?\s*\S", next_line.strip()):
                        break
                    if next_line.strip():
                        collected.append(next_line.strip())
                    if len(" ".join(collected)) >= 900:
                        break
                return " ".join(collected)[:1200]
        return ""

    @staticmethod
    def _evidence_structured_point(title: str, evidence: str) -> ExtractedKnowledgePoint | None:
        """Build a learnable point only when the heading has real source evidence."""
        source = " ".join((evidence or "").split()).strip()
        prompt_start = re.search(
            r"(?:\u63d0\u793a\u8bcd\u914d\u7f6e\u5982\u4e0b|\u4f60\u662f\u4e00\u4e2a\u4e13\u4e1a|\u4efb\u52a1\u8981\u6c42|\u8f93\u51fa\u683c\u5f0f)",
            source,
        )
        if prompt_start:
            source = source[:prompt_start.start()].strip()
        if len(source) < 80:
            return None
        sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])", source) if len(part.strip()) >= 12]
        core_source = "".join(sentences[:3]) or source[:260]
        why_source = "".join(sentences[1:4]) or source[:220]
        example_source = next((part for part in sentences if any(word in part for word in ("例如", "场景", "应用", "案例", "用户"))), "")
        if not example_source:
            example_source = source[:220]
        return ExtractedKnowledgePoint(
            name=title[:80],
            description=core_source[:500],
            category="课程概念",
            difficulty="基础",
            importance_for_ai_pm=3,
            importance_for_interview=3,
            prerequisite="",
            core_explanation=f"{title}的核心不是只记定义，而是理解：{core_source[:300]}",
            why_explanation=f"之所以需要掌握{title}，是因为课程材料指出：{why_source[:240]}",
            teaching_example=f"课程中的具体依据是：{example_source[:260]} 学习时请沿着‘输入/条件 → 处理机制 → 输出影响’复述这段证据。",
            ai_pm_relevance=f"对 AI 产品经理而言，应根据上述证据判断{title}影响的产品环节、验收指标和落地风险，而不是只复述名词。",
            interview_requirements=["能结合课程证据解释定义和机制", "能说明一个真实产品场景中的输入、输出与指标"],
            unnecessary_detail=[],
        )

    @staticmethod
    def _is_generic_filler(*values: str, title: str = "") -> bool:
        text = " ".join(values)
        stable_markers = (
            "\u672c\u9875\u7684\u72ec\u7acb\u5b66\u4e60\u4e3b\u9898",
            "\u5efa\u7acb\u5b8c\u6574\u7684\u6280\u672f\u4e0e\u4ea7\u54c1\u5224\u65ad",
            "\u8bbe\u8ba1\u4e00\u4e2a\u5c0f\u573a\u666f\u5e76\u89c2\u5bdf\u8f93\u5165",
            "\u9700\u7406\u89e3\u5176\u5b9a\u4e49\u3001\u5173\u952e\u673a\u5236\u548c\u4ea7\u54c1\u5f71\u54cd",
        )
        if any(marker in text for marker in stable_markers):
            return True
        prompt_markers = (
            "\u4f60\u662f\u4e00\u4e2a\u4e13\u4e1a",
            "\u4efb\u52a1\u8981\u6c42",
            "\u8f93\u51fa\u683c\u5f0f",
            "\u6839\u636e\u7528\u6237\u63d0\u4f9b\u7684\u4ee5\u4e0b\u4fe1\u606f",
        )
        if sum(marker in text for marker in prompt_markers) >= 2:
            return True
        markers = ("是本页的独立学习主题", "理解", "有助于建立完整", "围绕", "小场景并观察输入", "判断方案价值、效果指标与落地风险")
        return len(text) < 180 or sum(marker in text for marker in markers) >= 2 or text.count(title) >= 4

    @staticmethod
    def _is_noise_title(value: str) -> bool:
        text = re.sub(r"\s+", "", value or "")
        if re.search(r"\{\{[^{}]+\}\}", text):
            return True
        return bool(re.search(
            r"(?:\u5e74\d{0,2}\u6708\u4efd|\u674e\u98de\u98de.*\u8054\u540d\u53d1\u8868|\u641c\u7d22\u70ed\u5ea6\u5f00\u59cb)",
            text,
        ))

    @staticmethod
    def _reconstruct_pdf_content(content: str) -> str:
        raw = (content or "").replace("\r", "\n").replace("\uf06c", "•")
        raw = re.sub(r"\[PDF\s+P\d+(?:[–-]\d+)?\]", "\n", raw, flags=re.I)
        raw = re.sub(r"(?<![A-Za-z])([A-Za-z]{3,})-\n([A-Za-z]{2,})", r"\1\2", raw)
        raw = re.sub(r"([\u4e00-\u9fff])\s*\n\s*([\u4e00-\u9fff])", r"\1\2", raw)
        lines = []
        for line in raw.splitlines():
            value = re.sub(r"\s+", " ", line).strip(" \t•·-—")
            if not value or re.fullmatch(r"(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,3}|版权.*|copyright.*)", value, re.I): continue
            if re.search(r"(?:扫码|公众号|www\.|https?://|仅供学习|保密资料)", value, re.I): continue
            lines.append(value)
        blocks, current = [], []
        for line in lines:
            bullet = bool(re.match(r"^(?:[一二三四五六七八九十]+[、.]|\d+[、.]|[•●▪*-])", line))
            if bullet and current: blocks.append(" ".join(current)); current = []
            current.append(line)
        if current: blocks.append(" ".join(current))
        return "\n".join(blocks)

    @staticmethod
    def _pdf_layout_lines(content: str) -> list[str]:
        """Clean PDF/PPT lines without destroying slide layout semantics."""
        lines = []
        for raw in (content or "").replace("\r", "\n").splitlines():
            value = re.sub(r"\s+", " ", raw).strip(" \t•·")
            if not value or re.fullmatch(r"\d{1,3}", value):
                continue
            if re.fullmatch(r"(?:产品经理理论课程|第一节|产品经理理论课程[｜|:]第一节)", value):
                continue
            value = re.sub(r"^产品经理理论课程\s*[｜|:]?\s*第一节\s*", "", value).strip()
            if re.search(r"^(?:copyright|www\.|https?://|仅供学习|扫码)", value, re.I):
                continue
            lines.append(value)
        return lines

    @classmethod
    def _pdf_title(cls, lines: list[str]) -> str:
        candidates = []
        for value in lines[:12]:
            value = re.sub(r"^(?:产品经理理论课程\s*[｜|:]?\s*第一节\s*)", "", value).strip()
            if not value or len(value) > 70:
                continue
            if re.match(r"^(?:授课目标|今日关键词|工具和技能|方法论框架|板书)\b", value):
                continue
            score = 0
            if "？" in value or "?" in value:
                score += 12
            if "：" in value or ":" in value:
                score += 3
            if any(word in value for word in ("不同阶段", "五要素", "竞品分析", "需求分析", "需求池", "范围层", "结构层", "框架层")):
                score += 6
            if len(value) <= 35:
                score += 3
            if not re.search(r"[。；，,]", value):
                score += 2
            candidates.append((score, len(value), value))
        if not candidates:
            return "课程主题"
        title = max(candidates, key=lambda item: (item[0], -item[1]))[2]
        title = re.split(r"(?:授课目标|今日关键词|工具和技能|方法论框架)", title)[0].strip(" ：:")
        title = re.sub(r"^第一节\s*[：:]\s*", "", title).strip()
        return title[:30].rstrip("，,：:") or "课程主题"

    @classmethod
    def _pdf_readable_text(cls, lines: list[str]) -> str:
        """Recover sentence boundaries and bullet structure from extracted slide lines."""
        output, bullets = [], []
        bullet_re = re.compile(r"^(?:[-–—•·▪▸]|\d+[.)、]|[一二三四五六七八九十]+[、.)])\s*")

        def flush_bullets():
            nonlocal bullets
            if bullets:
                output.append("重点包括：" + "、".join(bullets) + "。")
                bullets = []

        for index, value in enumerate(lines):
            is_bullet = bool(bullet_re.match(value))
            value = bullet_re.sub("", value).strip()
            if is_bullet or (len(value) <= 24 and index > 0 and lines[index - 1].endswith(("：", ":"))):
                if len(value) >= 2:
                    bullets.append(value.rstrip("。；;"))
                continue
            flush_bullets()
            if value.endswith(("。", "！", "？", ".", "!", "?", "；", ";")):
                output.append(value)
            elif len(value) <= 30 and index + 1 < len(lines):
                output.append(value + "：")
            else:
                output.append(value + "。")
        flush_bullets()
        return "\n".join(output)

    @staticmethod
    def _is_incomplete_fragment(value: str) -> bool:
        text = re.sub(r"\s+", "", value or "")
        if len(text) < 8 or re.search(r"(?:包括|以及|通过|用于|以|的|和|与|在|为|是)$", text): return True
        return bool(re.search(r"[：:]$|[，,]$", text))

    @classmethod
    def _filter_pdf_points(cls, points: list[ExtractedKnowledgePoint]) -> list[ExtractedKnowledgePoint]:
        result, seen = [], set()
        for point in points:
            name = re.sub(r"\s+", " ", (point.name or "")).strip(" -•·:：")
            if name in seen or cls._is_incomplete_fragment(name): continue
            if re.fullmatch(r"(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d+|P\d+)", name, re.I): continue
            if len(name) > 90 or re.search(r"(?:本科|学历|年以上|任职经验|结果导向|招聘|岗位要求)", name): continue
            text = " ".join((point.core_explanation, point.why_explanation, point.teaching_example, point.ai_pm_relevance))
            if cls._is_generic_filler(point.core_explanation, point.why_explanation, point.teaching_example, point.ai_pm_relevance, title=name) or len(text) < 120: continue
            point.name = name; seen.add(name); result.append(point)
        return result[:10]

    def reprocess_pdf_course(self, db: Session, course_id: int, page_start: int = 1, page_end: int | None = None) -> dict:
        """Rebuild an imported PDF/PPT range into a small semantic set and retire fragment KPs."""
        repository = Repository(db)
        pdf = db.query(PDFImport).filter_by(course_id=course_id).first()
        if not pdf or pdf.status != "READY": raise LookupError("PDF 不存在或尚未 READY。")
        page_end = page_end or pdf.page_count
        if page_start < 1 or page_start > page_end or page_end > pdf.page_count: raise ValueError("PDF 页码范围无效。")
        lessons = [x for x in repository.get_course(course_id).lessons if x.source_type == "PDF" and (x.source_page_start or 0) >= page_start and (x.source_page_end or 0) <= page_end]
        if not lessons: raise ValueError("范围内没有可学习正文。")
        # Older imports discarded short slides (<40 chars). Re-read the original
        # PDF during reprocess so every page remains available as source evidence.
        existing_pages = {x.source_page_start for x in lessons}
        if len(existing_pages) < (page_end - page_start + 1):
            try:
                import pymupdf as fitz
                with fitz.open(pdf.file_path) as document:
                    for number in range(page_start, page_end + 1):
                        if number in existing_pages:
                            continue
                        text = document[number - 1].get_text("text").strip()
                        if text:
                            item = Lesson(
                                course_id=course_id, title=f"{pdf.original_filename} · 第 {number} 页",
                                url=f"pdf://reprocess/{pdf.file_hash}#page={number}", content=text,
                                content_hash=hashlib.sha256(text.encode()).hexdigest(), source_type="PDF",
                                parser_version="pymupdf_semantic_v2", structural_integrity="PASS",
                                migration_status="REPROCESSED", source_file=pdf.file_path,
                                source_page_start=number, source_page_end=number)
                            db.add(item); lessons.append(item)
                db.flush()
            except Exception:
                pass
        anchor = sorted(lessons, key=lambda x: x.source_page_start or 0)[0]
        source = ""
        # PDF/PPT pages are evidence, not lessons. Reconstruct adjacent slides into
        # semantic ranges before extracting KPs; this also works when no LLM is configured.
        ordered = sorted(lessons, key=lambda x: x.source_page_start or 0)
        groups: list[list] = []
        for lesson in ordered:
            if not groups or len(groups[-1]) >= 3:
                groups.append([lesson])
            else:
                groups[-1].append(lesson)
        extracted = []
        for group in groups:
            start = group[0].source_page_start or page_start
            end = group[-1].source_page_end or start
            lines = []
            for item in group:
                lines.extend(self._pdf_layout_lines(item.content or ""))
            if not lines:
                continue
            title = self._pdf_title(lines)
            body_lines = [line for line in lines if line.strip(" ：:") != title.strip(" ：:")]
            readable = self._pdf_readable_text(body_lines)
            evidence = readable[:1800]
            source += evidence + "\n"
            extracted.append(ExtractedKnowledgePoint(
                name=title or f"课程主题 {start}-{end}", description=evidence[:300],
                category="PDF Section", difficulty="基础", importance_for_ai_pm=4,
                importance_for_interview=4, prerequisite="", core_explanation=evidence[:700],
                why_explanation=f"本节围绕“{title}”组织内容，需结合相邻页面理解其产品判断与设计边界。",
                teaching_example=(evidence[300:800] if len(evidence[300:800]) >= 20 else evidence[:500]),
                ai_pm_relevance="AI PM 可据此明确目标、范围、用户路径、验证指标与落地风险。",
                interview_requirements=["能复述核心方法", "能结合产品场景判断"], unnecessary_detail=[]
            ))
            for item in group:
                item.chapter_title = "产品经理理论课程"
                item.section_title = title
                item.structural_integrity = "PASS"
                item.content_pipeline_version = "pdf_semantic_reconstruction_v1"
        if not extracted:
            pdf.reason_code = "NO_SECTION_FORMED"
            pdf.status = "FAILED"
            db.commit()
            raise RuntimeError("STRUCTURAL_RECONSTRUCTION_FAILED：未形成可学习 Section")
        old = db.query(KnowledgePoint).join(Lesson).filter(Lesson.course_id == course_id).all()
        for point in old:
            point.category = "RETIRED"
        saved = repository.replace_knowledge_points(anchor, extracted)
        for index, point in enumerate(saved):
            group = groups[index]
            start = group[0].source_page_start or page_start
            end = group[-1].source_page_end or start
            point.source_page = f"PDF P{start}-{end}"
            point.source_url = f"pdf://course/{course_id}#page={start}-{end}"
        pdf.section_count = len(extracted)
        pdf.page_quality_score = min(100, round(sum(min(100, len(x.content or "")) for x in ordered) / max(1, len(ordered))))
        pdf.section_quality_score = 80 if len(extracted) >= 3 else 60
        pdf.knowledge_quality_score = 80 if saved else 0
        pdf.reason_code = ""
        pdf.status = "READY" if saved else "FAILED"
        pdf.error_message = "" if saved else "KP_EXTRACTION_FAILED"
        db.commit()
        return {"course_id": course_id, "page_start": page_start, "page_end": page_end,
                "page_count": pdf.page_count, "ocr_pages": pdf.ocr_page_count,
                "total_clean_text_length": sum(len(self._reconstruct_pdf_content(x.content or "")) for x in ordered),
                "section_count": len(extracted),
                "sections": [{"title": p.name, "source_page_start": groups[i][0].source_page_start,
                              "source_page_end": groups[i][-1].source_page_end} for i, p in enumerate(extracted)],
                "knowledge_point_count": len(saved), "knowledge_point_titles": [p.name for p in saved],
                "course_summary": self._course_summary(type("Scope", (), {"source_type":"PDF", "content":source})(), saved)}
        specs = [
            ("AI产品经理的价值与岗位定位", ("价值", "产品经理"), "AI产品经理的核心价值在于把业务问题转化为可验证的AI产品目标，并协调数据、算法、工程和业务团队落地。", "AI能力只有嵌入真实业务流程并产生可衡量结果，才形成产品价值。", "面对需要大规模识别、生成或预测的业务问题，先定义用户结果和成功指标，再判断是否适合引入模型。", "产品经理要决策应用边界、数据投入、效果指标和上线风险。"),
            ("生成式AI与大模型的产品变化", ("生成式", "Token", "大模型"), "生成式AI不只做分类或识别，还能逐步生成文本、图像、表格等有意义的内容；Token是模型处理和生成信息的基本单位。", "生成能力扩大了产品交互和自动化边界，也带来事实性、成本和可控性问题。", "在问答产品中让模型生成答案，同时要求引用可信资料并对不确定内容拒答。", "AI PM需要设计提示、上下文、评估集和安全边界，并监控质量、延迟与成本。"),
            ("AI产品经理与算法工程师的协作边界", ("算法工程师", "模型", "bad case"), "AI PM需要把业务目标转化为模型目标、数据要求和可验收指标，并通过bad case定位能力边界。", "模型效果不是一次需求宣讲即可确定，需要多轮沟通、数据分析和误差归因。", "评论意向识别效果不佳时，联合算法团队按数据分布、标签质量和错误类型逐层定位。", "产品经理要定义模型目标、验收口径、迭代节奏及算法和工程的协作接口。"),
            ("AI典型行业应用与大模型生态", ("医疗", "金融", "LLM", "行业"), "AI已在医疗、金融、教育和城市等领域形成应用，LLM的泛化能力进一步扩大了可落地场景。", "行业场景的价值取决于数据质量、专业约束、责任边界和实际工作流，而不是模型参数本身。", "医疗影像辅助诊断可以提高筛查效率，但最终诊断仍需专业人员复核。", "AI PM要评估行业数据、合规要求、风险等级、人工兜底和效果指标。"),
            ("AI产品经理的核心职责与能力模型", ("职责", "需求", "方案", "协作"), "AI PM负责制定应用目标、理解用户需求、输出产品方案、推动跨团队落地，并持续分析上线数据。", "AI产品同时受模型能力、数据和工程约束，要求产品经理具备技术敏感度和跨团队沟通能力。", "设计智能客服时，先定义问题覆盖率和转人工规则，再与算法、工程共同确定实现方案。", "AI PM要平衡用户价值、模型效果、研发成本、上线风险和后续运营。"),
            ("AI产品从设计到上线的效果评估", ("评估", "指标", "上线", "数据"), "AI产品需要从目标、数据、模型、交互到上线监控形成闭环，不能只看离线准确率。", "线上用户分布和真实任务会变化，必须用多维指标和bad case持续验证产品是否有效。", "上线摘要功能后同时观察事实准确率、采纳率、响应时延、投诉率和单位调用成本。", "AI PM应建立离线评估集、线上监控、灰度策略和问题复盘机制。"),
        ]
        selected = [s for s in specs if any(k.casefold() in source.casefold() for k in s[1])]
        if len(selected) < 3: selected = specs[:3]
        old = db.query(KnowledgePoint).join(Lesson).filter(Lesson.course_id == course_id).all()
        for point in old:
            point.category = "Section"; point.core_explanation = point.why_explanation = point.teaching_example = point.ai_pm_relevance = ""
        extracted = [ExtractedKnowledgePoint(name=s[0], description=s[2], category="PDF主题", difficulty="基础", importance_for_ai_pm=4, importance_for_interview=4, prerequisite="", core_explanation=s[2], why_explanation=s[3], teaching_example=s[4], ai_pm_relevance=s[5], interview_requirements=["能解释核心机制", "能结合产品场景"], unnecessary_detail=[]) for s in selected]
        saved = repository.replace_knowledge_points(anchor, extracted)
        for point in saved: point.source_page = f"PDF P{page_start}–{page_end}"; point.source_url = f"pdf://course/{course_id}#page={page_start}"
        db.commit()
        return {"course_id": course_id, "page_start": page_start, "page_end": page_end, "knowledge_point_count": len(saved), "knowledge_point_titles": [p.name for p in saved], "summary": self._course_summary(type("Scope", (), {"source_type":"PDF", "content":source})(), saved)}

    def reprocess_interactive_lesson(self, db: Session, lesson_id: int) -> dict:
        repository = Repository(db); lesson = repository.get_lesson(lesson_id)
        if not lesson: raise LookupError("课程页面不存在。")
        source = lesson.content or ""; matches = list(re.finditer(r"(?im)^MODULE\s+\d+\s*$", source))
        if len(source) < 1500 or len(matches) < 2: raise ValueError("页面教学正文不足，未按交互课程重处理。")
        sections = []
        for index, match in enumerate(matches):
            chunk = source[match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(source)]
            lines = [x.strip() for x in chunk.splitlines() if x.strip()]
            title = next((x for x in lines[1:4] if len(x) >= 6), f"交互课程模块 {index + 1}")
            evidence = " ".join(lines[1:])[:1600]
            evidence_sentence = re.split(r"(?<=[。！？.!?])\s+", evidence)[0][:220]
            sections.append(ExtractedKnowledgePoint(
                name=title[:100], description=evidence[:280], category="交互课程模块", difficulty="基础",
                importance_for_ai_pm=4, importance_for_interview=4, prerequisite="",
                core_explanation=evidence[:500],
                why_explanation=f"本模块的关键问题是：{evidence_sentence or title} 这决定了Agent在真实任务中的行为边界与可控性。",
                teaching_example=f"先运行“{title}”中的演示，记录输入、模型动作和工具返回值；再改变一个条件，比较结果如何变化。",
                ai_pm_relevance=f"落地{title}时，AI PM应把上述行为转成可验收指标，并明确人工确认、失败兜底和成本/延迟预算。",
                interview_requirements=["能解释模块核心机制", "能结合产品场景说明取舍"], unnecessary_detail=[]))
        old = db.query(KnowledgePoint).filter(KnowledgePoint.lesson_id == lesson.id).all()
        for point in old: point.category = "Section"; point.core_explanation = point.why_explanation = point.teaching_example = point.ai_pm_relevance = ""
        saved = repository.replace_knowledge_points(lesson, sections)
        for point in saved: point.source_page = "交互课程完整页面"; point.source_url = lesson.url
        lesson.structural_integrity = "PASS"; lesson.content_pipeline_version = "interactive_lesson_v1"; db.commit()
        return {"lesson_id": lesson.id, "content_type": "INTERACTIVE_LESSON", "heading_count": len(matches), "top_level_sections": len(saved), "knowledge_point_count": len(saved), "knowledge_point_titles": [p.name for p in saved], "summary": f"本课通过交互演示讲解{ '、'.join(p.name for p in saved)}，帮助学习者理解Agent架构、上下文与工具协作、权限边界以及评估方法。"[:180]}

    @staticmethod
    def evaluate_learning_content_eligibility(content: str) -> str:
        metrics = StudyService.interactive_content_debug(content)
        if metrics["clean_text_length"] < 40:
            return "EMPTY"
        if metrics["substantive_text_length"] >= 1500 and (metrics["heading_count"] >= 4 or metrics["paragraph_count"] >= 8 or metrics["table_count"] >= 1):
            return "INTERACTIVE_LESSON" if metrics["interactive_control_count"] or metrics["table_count"] else "ARTICLE"
        if metrics["link_count"] >= 8 and metrics["substantive_text_length"] < 600:
            return "LINK_HUB"
        # A short Feishu/product-design document can contain a dense outline
        # and business evidence while mentioning a click action.  That wording
        # is not evidence of an interactive navigation page.
        if metrics["substantive_text_length"] >= 250 and metrics["heading_count"] >= 3:
            return "ARTICLE"
        if metrics["interactive_control_count"] and metrics["substantive_text_length"] < 500:
            return "INTERACTIVE_INDEX"
        return "ARTICLE"

    @staticmethod
    def interactive_content_debug(content: str) -> dict:
        text = " ".join((content or "").split())
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        heading_count = sum(1 for line in lines if len(line) <= 100 and (line.upper().startswith("MODULE") or re.match(r"^(?:#{1,6}|\d+[.)、])\s*\S", line)))
        paragraph_count = sum(1 for line in lines if len(line) >= 45 and not re.match(r"^(?:[•●▪*-]|\d+[.)、])", line))
        button_count = len(re.findall(r"(?:▶|运行|重置|点击|播放|暂停|发起一次工具调用)", content or "", re.I))
        link_count = len(re.findall(r"https?://|\[[^\]]+\]\([^)]*\)", content or "", re.I))
        substantive = re.sub(r"(?:▶|↺|点击任意节点|当前页面|Copyright|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", "", text, flags=re.I)
        return {"raw_text_length": len(content or ""), "clean_text_length": len(text), "substantive_text_length": len(substantive), "heading_count": heading_count, "paragraph_count": paragraph_count, "table_count": int("维度" in text and "控制流" in text), "button_count": button_count, "interactive_control_count": button_count, "link_count": link_count, "article_found": False, "main_found": False, "body_fallback_used": True, "source_quality_score": min(100, round(len(substantive) / 30 + heading_count * 2))}

    @classmethod
    def _evidence_point(cls, title: str, evidence: str) -> ExtractedKnowledgePoint | None:
        if len(evidence.strip()) < 40:
            return None
        first = evidence.split("。", 1)[0].strip() + "。"
        return ExtractedKnowledgePoint(
            name=title[:80], description=first[:300], category="课程内容", difficulty="基础",
            importance_for_ai_pm=3, importance_for_interview=3, prerequisite="",
            core_explanation=evidence[:700],
            why_explanation=f"课程指出：{evidence[:450]}",
            teaching_example=f"以课程中的事实为例：{evidence[:500]}",
            ai_pm_relevance=f"产品决策应围绕课程提到的约束展开：{evidence[:450]}",
            interview_requirements=["能复述课程中的关键事实", "能说明该事实对方案选择的影响"],
            unnecessary_detail=[],
        )

    def _reprocess_feishu_lesson(self, db: Session, lesson) -> dict:
        """Turn Feishu body evidence into one readable lesson, never a page chrome or TOC card."""
        repository = Repository(db)
        ignored = ("header-v2", "飞书云文档", "最新修改时间", "评论（", "跳转至首条评论", "帮助中心", "快捷键")
        # Snapshots from a virtualized Feishu page can begin with a table of
        # contents or side-panel text. The document title appears again when
        # the real body is rendered; use that last occurrence as the evidence
        # boundary whenever it is available.
        source = lesson.content or ""
        document_title = (lesson.title or "").replace("\u200b", "").strip()
        title_positions = [match.start() for match in re.finditer(re.escape(document_title), source)] if document_title else []
        if title_positions:
            source = source[title_positions[-1]:]
        lines = [line.strip() for line in source.splitlines() if line.strip()]
        lines = [line for line in lines if not any(token in line for token in ignored) and line not in {"两光年", "0 字", "•", "◦"}]
        heading = next((line for line in lines if re.match(r"^[一二三四五六七八九十]+[、.]\s*.+", line)), lesson.title)
        title = re.sub(r"^[一二三四五六七八九十]+、", "", heading).strip()[:100]
        body = [line for line in lines if len(line) >= 35 and line != heading and not re.match(r"^(?:[0-9]+(?:\.[0-9]+)*|[一二三四五六七八九十]+)、", line)]
        if not body:
            raise ValueError("飞书文档尚未抓取到可教学正文，已避免生成目录型知识点。")
        core = body[0][:700]
        metrics = "；".join(line for line in body[1:] if any(word in line for word in ("北极星", "指标", "护栏", "负反馈", "投诉")))[:450]
        inputs = "；".join(line for line in body if any(word in line for word in ("输入", "行为", "观看", "提交线索")))[:450]
        point = ExtractedKnowledgePoint(
            name=title, description=core[:300], category="产品方案", difficulty="进阶",
            importance_for_ai_pm=4, importance_for_interview=4, prerequisite="理解用户行为数据与线索转化漏斗。",
            core_explanation=core,
            why_explanation=metrics or "该方案需要同时提升线索质量，并控制对低意向用户的打扰和负反馈。",
            teaching_example=inputs or "根据用户行为信号输出意向分，并映射为 PLC 是否展示、展示强度和频控动作。",
            ai_pm_relevance="AI PM 需要定义标签时间窗、阈值与频控规则，并以线索提交率、合格线索率和负反馈率共同验收。",
            interview_requirements=["能说明模型输出如何驱动产品动作", "能同时定义增长指标与体验护栏"],
            unnecessary_detail=["未在文档正文展开的模型参数", "没有证据的特征字段细节"],
        )
        saved = repository.replace_knowledge_points(lesson, [point])
        for stale in repository.list_knowledge_points(lesson.id):
            if stale.id != saved[0].id:
                stale.category = "Section"
                stale.core_explanation = stale.why_explanation = ""
                stale.teaching_example = stale.ai_pm_relevance = ""
        lesson.parser_version = "feishu_docx_v2"
        lesson.structural_integrity = "PASS"
        lesson.content_pipeline_version = "feishu_evidence_v1"
        db.commit()
        return {"lesson_id": lesson.id, "title": lesson.title, "structural_heading_count": 1,
                "knowledge_point_count": 1, "knowledge_point_titles": [point.name], "repaired": True}

    def reprocess_lesson_structure(self, db: Session, lesson_id: int) -> dict:
        """Repair legacy GitBook pages that were stored as one giant knowledge point.

        Existing point IDs are retained (and therefore keep their attempts/mastery history);
        additional structural topics are added as new points. This endpoint intentionally does
        not touch any scoring rules.
        """
        repository = Repository(db)
        lesson = repository.get_lesson(lesson_id)
        if not lesson:
            raise LookupError("课程页面不存在，请先采集课程。")
        if "feishu.cn/docx/" in (lesson.url or ""):
            return self._reprocess_feishu_lesson(db, lesson)
        original_title = lesson.title or ""
        lesson.title = sanitize_site_title_suffix(original_title) or original_title
        titles = self._structural_heading_titles(lesson.content or "")
        if self.evaluate_learning_content_eligibility(lesson.content) in {"INTERACTIVE_INDEX", "NAVIGATION_PAGE", "LINK_HUB"}:
            for point in repository.list_knowledge_points(lesson.id):
                point.category = "Section"
                point.core_explanation = point.why_explanation = point.teaching_example = point.ai_pm_relevance = ""
            lesson.structural_integrity = "PASS"
            lesson.content_pipeline_version = "learning_content_v3"
            db.commit()
            return {"lesson_id": lesson.id, "title": lesson.title, "title_changed": lesson.title != original_title,
                    "structural_heading_count": len(titles), "knowledge_point_count": 0, "repaired": True,
                    "content_type": "INTERACTIVE_INDEX"}
        points = repository.list_knowledge_points(lesson.id)
        repaired = False
        if len(titles) >= 3 and len(points) <= 1:
            # Reuse the existing record for the first topic so historical attempts remain linked.
            if points:
                points[0].name = titles[0]
            extracted = [
                ExtractedKnowledgePoint(
                    name=title[:80],
                    description=f"本节聚焦{title}的核心概念与应用边界。",
                    category="课程章节",
                    difficulty="基础",
                    importance_for_ai_pm=3,
                    importance_for_interview=3,
                    prerequisite="",
                    core_explanation=f"{title}是本页的独立学习主题，需理解其定义、关键机制和产品影响。",
                    why_explanation=f"理解{title}有助于建立完整的技术与产品判断。",
                    teaching_example=f"在实际AI产品中，可围绕{title}设计一个小场景并观察输入、处理与结果。",
                    ai_pm_relevance="AI产品经理需要据此判断方案价值、效果指标与落地风险。",
                    interview_requirements=["能解释核心概念", "能结合产品场景"],
                    unnecessary_detail=[],
                )
                for title in titles[:20]
            ]
            for item in extracted:
                self._normalize_point_metadata(item)
            points = repository.replace_knowledge_points(lesson, extracted)
            repaired = True
        # Refresh legacy/template teaching from the matching source section. Never retain
        # title-only filler when the page contains usable evidence.
        evidence_points = []
        for point in points:
            evidence_point = self._evidence_point(point.name, self._source_evidence(lesson.content or "", point.name))
            if evidence_point and not self._is_generic_filler(evidence_point.core_explanation, evidence_point.why_explanation, title=point.name):
                evidence_points.append(evidence_point)
        if not evidence_points and len((lesson.content or "").strip()) >= 40:
            fallback_point = self._evidence_point(lesson.title, lesson.content)
            if fallback_point:
                evidence_points.append(fallback_point)
        if evidence_points:
            repository.replace_knowledge_points(lesson, evidence_points)
            points = repository.list_knowledge_points(lesson.id)
            repaired = True
        evidence_names = {item.name for item in evidence_points}
        for point in points:
            if point.name not in evidence_names and self._is_generic_filler(
                point.core_explanation or "", point.why_explanation or "", title=point.name
            ):
                # A heading without supporting prose is a section, not a teachable KP.
                point.category = "Section"
                point.core_explanation = point.why_explanation = ""
                point.teaching_example = point.ai_pm_relevance = ""
                point.description = "课程章节标题，正文证据不足，暂不生成知识点教学内容。"
                repaired = True
        db.commit()
        db.commit()
        return {
            "lesson_id": lesson.id,
            "title": lesson.title,
            "title_changed": lesson.title != original_title,
            "structural_heading_count": len(titles),
            "knowledge_point_count": len(points),
            "repaired": repaired,
        }

    @staticmethod
    def _is_gitbook_lesson(lesson) -> bool:
        value = f"{lesson.title or ''} {lesson.url or ''}".casefold()
        return lesson.source_type == "GITBOOK" or "gitbook" in value or "· gitbook" in value

    def reprocess_all_gitbook(self, db: Session, force: bool = False) -> dict:
        repository = Repository(db)
        lessons = [item for item in repository.list_lessons_all() if self._is_gitbook_lesson(item)]
        processed = skipped = failed = 0
        for lesson in lessons:
            if not force and lesson.parser_version == "new_gitbook_v2" and lesson.structural_integrity == "PASS":
                skipped += 1
                continue
            try:
                result = self.reprocess_lesson_structure(db, lesson.id)
                lesson.source_type = "GITBOOK"
                lesson.parser_version = "new_gitbook_v2"
                lesson.structural_integrity = "PASS" if result["knowledge_point_count"] > 1 or result["structural_heading_count"] < 3 else "FAILED_STRUCTURE"
                lesson.migration_status = "RESTRUCTURED" if result["repaired"] else "NORMALIZED"
                processed += 1
            except (LookupError, ValueError, RuntimeError):
                lesson.structural_integrity = "FAILED_STRUCTURE"
                failed += 1
        db.commit()
        return {"total_gitbook_pages": len(lessons), "processed": processed, "already_v2": skipped, "failed_pages": failed}

    async def ask(
        self,
        db: Session,
        question: str,
        course_id: int | None,
        lesson_id: int | None = None,
    ) -> tuple[str, list[dict]]:
        repository = Repository(db)
        lexical = repository.search_lessons_lexical(
            question, course_id=course_id, lesson_id=lesson_id, limit=5
        )
        vector = knowledge_base.search(question, course_id=course_id, limit=7)
        matches: list[dict] = []
        seen_lesson_ids: set[int] = set()
        for item in [*lexical, *vector]:
            lesson_key = int(item["lesson_id"])
            if lesson_key not in seen_lesson_ids:
                matches.append(item)
                seen_lesson_ids.add(lesson_key)
            if len(matches) == 4:
                break
        if not matches:
            return "知识库中还没有相关内容，请先采集课程。", []
        context = "\n\n".join(
            f"资料 {index + 1}（{item['title']}）:\n{item['text']}"
            for index, item in enumerate(matches)
        )
        result = await llm_service.complete_structured(
            KnowledgeQAOutput,
            tutor_system(
                "优先依据给定课程资料回答，并在课程要点中用[资料N]标注。课程不足时允许使用"
                "模型通用知识补充，但必须放进general_supplement，不能伪装成课程内容或网络来源。"
                "第一句直接回答问题；随后最多5个短要点，总体适合快速学习。"
            ),
            f"课程资料：\n{context}\n\n学习者问题：{question}",
            fallback=lambda: KnowledgeQAOutput(
                direct_answer="模型暂时未能生成完整答案，请稍后重试。",
                course_points=["已检索到相关课程页面，但本次模型响应失败。"],
                general_supplement=[],
                boundary_note="未使用模型通用补充。",
            ),
        )
        answer_parts = [result.direct_answer]
        if result.course_points:
            answer_parts.append(
                "课程依据：\n" + "\n".join(f"- {item}" for item in result.course_points)
            )
        if result.general_supplement:
            answer_parts.append(
                "模型通用补充（未联网核验）：\n"
                + "\n".join(f"- {item}" for item in result.general_supplement)
            )
        if result.boundary_note:
            answer_parts.append(f"来源边界：{result.boundary_note}")
        answer = "\n\n".join(answer_parts)
        sources_by_id = {}
        for item in matches:
            sources_by_id[item["lesson_id"]] = {
                "lesson_id": item["lesson_id"],
                "title": item["title"],
                "url": item["url"],
            }
        sources = list(sources_by_id.values())
        repository.save_study_record(question, answer, list(sources_by_id))
        return answer, sources

    @staticmethod
    def _fallback_extraction(title: str, content: str) -> KnowledgeExtractionOutput:
        compact = " ".join(content.split())
        sentences = [part.strip() for part in compact.replace("！", "。\n").replace("？", "。\n").split("。") if part.strip()]
        excerpt = StudyService._minimum_teaching_text(
            "。".join(sentences[:2]) + ("。" if sentences else ""),
            f"本知识点来自课程页面《{title}》，需要结合页面内容理解其原因和作用。",
        )
        point = ExtractedKnowledgePoint(
            name=title[:300],
            description=excerpt,
            category="课程核心概念",
            difficulty="基础",
            importance_for_ai_pm=3,
            importance_for_interview=3,
            prerequisite="以课程原文列出的前置知识为准",
            core_explanation=excerpt,
            why_explanation="它会改变信息的处理方式和关键约束，因此最终影响模型效果与产品结果。",
            teaching_example=(
                f"例如，在一个具体产品任务中观察“{title}”的输入、处理过程和输出，"
                "再判断结果是否符合业务目标。"
            ),
            ai_pm_relevance=(
                "AI 产品经理需要用它判断方案是否匹配产品目标，并评估效果、成本、延迟和风险。"
            ),
            interview_depth="P1",
            interview_value=3,
            interview_requirements=["能解释是什么和为什么", "能说明产品场景与基本风险"],
            unnecessary_detail=["数学证明", "底层代码实现"],
        )
        return KnowledgeExtractionOutput(course_summary=excerpt, knowledge_points=[point])

    @classmethod
    def _fallback_pdf_extraction(cls, content: str) -> KnowledgeExtractionOutput:
        """Build one evidence-backed semantic slide topic, never one point per OCR line."""
        lines = [line.strip() for line in cls._reconstruct_pdf_content(content).splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("PDF 页面没有足够正文用于生成知识点。")
        original_lines = [re.sub(r"\[PDF\s+P\d+(?:[–-]\d+)?\]", "", line, flags=re.I).strip() for line in (content or "").splitlines()]
        source_heading = next((line for line in original_lines if 6 <= len(line) <= 80 and not re.search(r"[，,。]", line)), None)
        source_heading = source_heading or next((line for line in lines if len(line) <= 45 and not re.search(r"[，,。]", line)), "PDF资料核心主题")
        evidence = " ".join(line for line in lines if line != source_heading).strip() or lines[0]
        point = cls._evidence_point(source_heading, evidence)
        if point is None:
            raise RuntimeError("PDF 页面正文证据不足，未生成占位知识点。")
        return KnowledgeExtractionOutput(
            course_summary=" ".join(lines)[:700],
            knowledge_points=[point],
        )

    @staticmethod
    def _fallback_question(
        point,
        difficulty: int,
        stage: str,
        category: str = "AI技术理解",
        interview_depth: str = "P1",
        target_role: str = "general_ai_pm",
    ) -> GeneratedQuestion:
        from app.services.public_practice import employment_question

        authored = employment_question(point, target_role, difficulty, stage)
        if authored:
            return authored
        question_type = QUESTION_TYPE_BY_CATEGORY[category]
        if stage in {"targeted", "retest"}:
            text = (
                f"观察一个使用“{point.name}”的具体场景：训练或历史数据表现很好，"
                "但新数据或线上效果明显下降。你会如何判断问题，并说明最关键的原因？"
            )
            question_type = "场景Case题"
        elif any(term in point.name.casefold() for term in ("分类阈值", "逻辑回归")) and category in {
            "技术选型 / Trade-off",
            "产品设计 / Case",
        }:
            text = "如果模型输出用户流失概率，你会直接把0.5作为分类阈值吗？为什么？"
        elif category == "技术选型 / Trade-off":
            text = f"在什么场景下你会选择“{point.name}”，什么情况下会换用其他方案？为什么？"
        elif category == "产品设计 / Case":
            text = f"如果把“{point.name}”用于一个AI产品，你会如何设计方案并判断它是否有效？"
        elif category == "LLM / RAG / Agent应用":
            text = f"“{point.name}”在LLM、RAG或Agent产品中能解决什么问题？有哪些风险？"
        elif category == "项目深挖 / Troubleshooting":
            text = f"使用“{point.name}”后线上效果不理想，你会按什么顺序定位问题？"
        elif difficulty >= 2:
            text = f"请说明“{point.name}”的核心机制，并分析它对AI产品设计的影响。"
        else:
            text = f"请用自己的话解释“{point.name}”是什么、为什么有用。"
        public_definition = None
        if (getattr(point, "source_url", "") or "").startswith("public://"):
            from app.services.public_curriculum import lesson_definition

            public_definition = lesson_definition(point.lesson_id)
            if public_definition:
                text = f"{public_definition['practice_task']} 请围绕“{point.name}”说明机制、适用边界和判断依据。"
                if stage in {"targeted", "retest"}:
                    text += "如果关键资料不足或使用条件变化，你会先核查哪项假设，为什么？"
                question_type = "场景Case题"
        result = GeneratedQuestion(
            question_type=question_type,
            difficulty=difficulty,
            question=text,
            assessment_focus=[point.name, "核心作用", "表达结构"],
            interview_category=category,
            target_role=target_role,
            interview_value=point.interview_value,
            interview_depth=interview_depth,
            why_interviewer_asks="用于判断候选人能否把技术机制转化为产品判断，而不是只会背术语。",
            must_have_points=["结论正确", "说明原因", "联系产品场景"],
            bonus_points=["说明选型或指标权衡"],
            unnecessary_detail="题目未要求的公式推导、算法证明或代码实现不属于必答内容。",
            question_fingerprint=QuestionFingerprint(
                knowledge_point=point.name,
                question_type=question_type,
                tested_skill=(
                    "scenario_application" if stage in {"targeted", "retest"}
                    else "technical_reasoning"
                ),
                scenario=(
                    "train_test_or_online_gap" if stage in {"targeted", "retest"}
                    else "concept_explanation"
                ),
                reasoning_target=(
                    "identify_cause_from_observed_metrics"
                    if stage in {"targeted", "retest"}
                    else f"explain_{point.name}_core_mechanism"
                ),
                expected_answer_dimensions=["结论", "原因", "因果关系"],
            ),
        )
        if public_definition:
            result.assessment_focus = [point.name, "适用边界", "资料依据", "产品取舍"]
            result.question_fingerprint.scenario = f"public_lesson_{point.lesson_id}_{stage}"
        return result

    @staticmethod
    def _normalize_point_metadata(point) -> None:
        point.interview_depth, point.interview_value = normalized_interview_profile(
            point.name, point.interview_depth, point.interview_value
        )
        fixed_boundaries = interview_boundaries(point.name)
        if fixed_boundaries:
            point.interview_requirements, point.unnecessary_detail = fixed_boundaries
        if not point.interview_requirements:
            point.interview_requirements = [
                "能解释是什么、为什么和核心机制",
                "能说明使用场景、方案选择、基本指标与风险",
            ]
        if not point.unnecessary_detail:
            point.unnecessary_detail = ["数学推导", "算法证明", "具体代码实现"]

    @staticmethod
    def _point_context(point) -> str:
        return (
            f"知识点：{point.name}\n描述：{point.description}"
            f"\n核心解释：{point.core_explanation or point.level_1}"
            f"\n为什么：{point.why_explanation}"
            f"\n教学例子：{point.teaching_example}"
            f"\nAI PM关联：{point.ai_pm_relevance}"
        )

    async def _generate_question(
        self,
        repository: Repository,
        point,
        difficulty: int,
        stage: str,
        previous: list[tuple] | None = None,
        forced_category: str | None = None,
        forced_depth: str | None = None,
        targeted_angle: dict[str, str] | None = None,
        profile_override=None,
    ) -> GeneratedQuestion:
        previous_text = "\n".join(
            f"{attempt.question_type}（难度{attempt.difficulty}）：{score}分"
            for attempt, score in (previous or [])[-5:]
        )
        profile = profile_override or target_role_service.selected_profile(repository)
        from app.services.public_practice import employment_question

        authored = employment_question(point, profile.id, difficulty, stage)
        if authored:
            return authored
        category = forced_category or interview_priority_service.select_question_category(
            repository, profile
        )
        if point.interview_value < 4 and category in {
            "技术选型 / Trade-off",
            "产品设计 / Case",
            "项目深挖 / Troubleshooting",
        }:
            category = "AI技术理解"
        interview_depth = forced_depth or interview_priority_service.question_depth(
            repository, point, category, profile
        )
        recent_attempts = [item for item, _ in (previous or [])][-5:]
        public_context = ""
        is_public = (getattr(point, "source_url", "") or "").startswith("public://")
        if is_public:
            from app.services.public_curriculum import curriculum_sources, lesson_definition

            definition = lesson_definition(point.lesson_id)
            if definition:
                public_context = (
                    f"\n本节原创练习场景：{definition['practice_task']}"
                    f"\n依据资料：{json.dumps(curriculum_sources(definition['source_ids']), ensure_ascii=False)}"
                    "\n公开教材练习仅考给出的知识原理与场景，不复制外部题库，不编造教材未提供的事实。"
                    "例子和产品迁移属于原创教学补充，不宣称来自教材原例。"
                )
        # Public practice must not pull questions from a locally imported
        # private/purchased interview bank.
        if stage in {"initial", "probe"} and not is_public:
            bank_question = interview_bank_service.select_for_learning(
                repository.db, point, category
            )
            if bank_question:
                bank_question.target_role = profile.id
                bank_question.interview_depth = interview_depth
                question_diversity_service.ensure_fingerprint(bank_question, point.name)
                if not question_diversity_service.conflicts(bank_question, recent_attempts):
                    return bank_question
        generated = None
        for generation_index in range(3):
            generated = await llm_service.complete_structured(
                GeneratedQuestion,
                tutor_system(
                    "一次只生成1道可明确评分的问题，并完整输出question_fingerprint。补测必须针对"
                    "具体薄弱点换角度，禁止换句话重复原题。与最近5题比较时，要改变reasoning_target、"
                    "tested_skill或scenario。P1只考AI PM做判断、解释方案和沟通研发所需内容；禁止把"
                    "公式推导、算法证明或代码实现当作P1必答内容。"
                ),
                f"{self._point_context(point)}\n目标难度：{difficulty}\n阶段：{stage}"
                f"{public_context}"
                f"\n指定面试类别：{category}\n指定面试深度：{interview_depth}"
                f"\n目标岗位：{profile.name}\n岗位核心能力：{profile.core_skills}"
                f"\nCase重点：{profile.case_focus}\n项目深挖重点：{profile.project_focus}"
                f"\n面试价值：{point.interview_value}/5\n题型目标比例：{QUESTION_DISTRIBUTION}"
                f"\n本次薄弱点与换角要求：{json.dumps(targeted_angle or {}, ensure_ascii=False)}"
                f"\n历史表现：\n{previous_text or '暂无'}\n重复保护重试序号：{generation_index + 1}",
                fallback=lambda: self._fallback_question(
                    point, difficulty, stage, category, interview_depth, profile.id
                ),
            )
            generated.interview_category = category
            generated.interview_depth = interview_depth
            generated.interview_value = point.interview_value
            generated.target_role = profile.id
            if targeted_angle:
                generated.question_type = targeted_angle["question_type"]
                generated.question_fingerprint.tested_skill = targeted_angle["tested_skill"]
                generated.question_fingerprint.scenario = targeted_angle["scenario"]
                generated.question_fingerprint.reasoning_target = targeted_angle["reasoning_target"]
            else:
                generated.question_type = QUESTION_TYPE_BY_CATEGORY[category]
            if not generated.must_have_points:
                generated.must_have_points = ["结论正确", "解释原因", "形成产品判断"]
            if not generated.bonus_points:
                generated.bonus_points = ["说明指标、风险或Trade-off"]
            question_diversity_service.ensure_fingerprint(generated, point.name)
            if not question_diversity_service.conflicts(generated, recent_attempts):
                return generated
        fallback = self._fallback_question(
            point, difficulty, "targeted", category, interview_depth, profile.id
        )
        question_diversity_service.ensure_fingerprint(fallback, point.name)
        if targeted_angle:
            fallback.question_fingerprint.tested_skill = targeted_angle["tested_skill"]
            fallback.question_fingerprint.scenario = f"{targeted_angle['scenario']}_alternative"
            fallback.question_fingerprint.reasoning_target = targeted_angle["reasoning_target"]
        return fallback

    @staticmethod
    def _point_view(repository: Repository, point, profile=None) -> dict:
        profile = profile or target_role_service.selected_profile(repository)
        mastery = repository.get_mastery_score(point.id)
        importance = importance_engine.point_rating(repository, point)
        importance_label, importance_label_cn = LABELS[importance.dynamic_importance_score]
        role_readiness, role_ready = target_role_service.point_readiness(
            repository, point, profile
        )
        try:
            interview_requirements = json.loads(point.interview_requirements_json or "[]")
        except (TypeError, json.JSONDecodeError):
            interview_requirements = []
        try:
            unnecessary_detail = json.loads(point.unnecessary_detail_json or "[]")
        except (TypeError, json.JSONDecodeError):
            unnecessary_detail = []
        return {
            "id": point.id,
            "name": point.name,
            "description": point.description,
            "category": point.category,
            "difficulty": point.difficulty,
            "importance_for_ai_pm": point.importance_for_ai_pm,
            "importance_for_interview": point.importance_for_interview,
            "prerequisite": point.prerequisite,
            "source_page": point.source_page,
            "source_url": point.source_url,
            "core_explanation": point.core_explanation or point.level_1,
            "why_explanation": point.why_explanation,
            "teaching_example": point.teaching_example,
            "ai_pm_relevance": point.ai_pm_relevance,
            "extended_explanation": point.extended_explanation,
            "interview_depth": point.interview_depth,
            "interview_value": point.interview_value,
            "interview_requirements": interview_requirements,
            "unnecessary_detail": unnecessary_detail,
            "mastery_score": mastery.mastery_score if mastery else 0,
            "mastery_status": mastery.status if mastery else "未学习",
            "interview_readiness": role_readiness,
            "interview_ready": role_ready,
            "dynamic_importance_score": importance.dynamic_importance_score,
            "importance_label": importance_label,
            "importance_label_cn": importance_label_cn,
            "importance_reason": importance.importance_reason,
            "learning_priority_score": importance.learning_priority_score,
            "interview_status": mastery.interview_status if mastery else "NOT_TESTED",
            **coverage_service.view(repository.db, point),
        }

    @staticmethod
    def _point_priority(repository: Repository, point, profile=None) -> float:
        profile = profile or target_role_service.selected_profile(repository)
        readiness, _ = target_role_service.point_readiness(repository, point, profile)
        weakness_factor = 1 + (100 - readiness) / 100
        weakness_factor += min(0.5, len(repository.list_weaknesses(point.id)) * 0.2)
        role_relevance = target_role_service.relevance(profile, point) / 5
        return point.interview_value * weakness_factor * role_relevance

    async def start_mastery_loop(self, db: Session, lesson_id: int | None = None, course_id: int | None = None,
                                 scope_type: str | None = None, page_start: int | None = None,
                                 page_end: int | None = None, section_id: str | None = None,
                                 target_role: str | None = None) -> dict:
        repository = Repository(db)
        profile = target_role_service.get_profile(target_role) if target_role else target_role_service.selected_profile(repository)
        scope = None
        if course_id and scope_type:
            pdf = db.query(__import__('app.db.models', fromlist=['PDFImport']).PDFImport).filter_by(course_id=course_id).first()
            if not pdf or pdf.status != "READY":
                raise LookupError("PDF 尚未准备好，无法开始学习。")
            if scope_type not in {"ENTIRE_PDF", "SECTION", "PAGE_RANGE"}:
                raise ValueError("不支持的 PDF 学习范围。")
            if scope_type == "ENTIRE_PDF": page_start, page_end = 1, pdf.page_count
            if scope_type == "PAGE_RANGE" and (page_start is None or page_end is None or page_start > page_end or page_end > pdf.page_count):
                raise ValueError(f"页码范围无效：必须满足 1 <= start <= end <= {pdf.page_count}。")
            lessons = sorted([x for x in repository.get_course(course_id).lessons if x.source_type == "PDF"], key=lambda x: x.source_page_start or 0)
            if scope_type == "SECTION":
                selected = [x for x in lessons if (not section_id or section_id == "all" or x.section_title == section_id or x.chapter_title == section_id)]
                if not selected: raise ValueError("未找到所选 PDF 章节。")
                page_start, page_end = min(x.source_page_start for x in selected), max(x.source_page_end for x in selected)
            selected = [x for x in lessons if (x.source_page_start or 0) >= page_start and (x.source_page_end or 0) <= page_end]
            if not selected: raise ValueError("所选范围没有可学习正文。")
            lesson = copy.copy(selected[0])
            raw = "\n\n".join(f"[PDF P{x.source_page_start}]\n{x.content}" for x in selected)
            # Internal aggregation units stay invisible to the learner; repeated lines are removed before synthesis.
            chunks = [raw[i:i + 12000] for i in range(0, len(raw), 12000)]
            seen, clean_chunks = set(), []
            for chunk in chunks:
                lines = []
                for line in chunk.splitlines():
                    key = re.sub(r"\s+", "", line)
                    if key and key in seen: continue
                    if key: seen.add(key)
                    lines.append(line)
                clean_chunks.append("\n".join(lines))
            lesson.content = "\n\n".join(clean_chunks)
            lesson.title = f"{pdf.original_filename} · P{page_start}–{page_end}"
            scope = {"scope_type": scope_type, "source_pdf_id": pdf.id, "page_start": page_start, "page_end": page_end, "section_id": section_id or "", "label": f"PDF P{page_start}–{page_end}"}
        else:
            lesson = repository.get_lesson(lesson_id) if lesson_id else None
        if not lesson:
            raise LookupError("课程页面不存在，请先采集课程。")
        # Older crawls may contain only a short shell/placeholder for this
        # interactive page. Reuse a complete /sources/index.html capture from
        # the same course so learners do not hit the navigation dead end.
        if not scope and lesson.source_type != "PDF" and len((lesson.content or "").strip()) < 1500:
            lesson_url = (lesson.url or "").split("#", 1)[0]
            if "Agent%E4%BA%BA交互" in lesson_url or "Agent%E4%BA%A4%E4%BA%92" in lesson_url or "Agent交互" in lesson_url:
                candidates = [x for x in repository.get_course(lesson.course_id).lessons
                              if x.id != lesson.id and x.source_type != "PDF"
                              and len((x.content or "").strip()) >= 1500
                              and "/sources/index.html" in (x.url or "")]
                # Duplicated imports can place the shell in a different course;
                # match the canonical URL globally as a last resort.
                if not candidates:
                    from app.db.models import Lesson as LessonModel
                    candidates = [x for x in db.query(LessonModel).all()
                                  if x.id != lesson.id and x.source_type != "PDF"
                                  and len((x.content or "").strip()) >= 1500
                                  and "/sources/index.html" in (x.url or "")
                                  and "Agent%E4%BA%A4%E4%BA%92" in (x.url or "")]
                if candidates:
                    same_path = [x for x in candidates if (x.url or "").split("#", 1)[0] == lesson_url]
                    lesson = max(same_path or candidates, key=lambda x: len(x.content or ""))
        if len((lesson.content or "").strip()) < 40:
            raise RuntimeError("该课程页面没有提取到正文，已停止生成模板知识点。请重新导入或执行 OCR。")
        # A Feishu doc can legitimately contain words such as "点击 PLC".
        # That is a product action in the course evidence, not an interactive
        # course control. Never route Feishu documents to the MODULE-based
        # interactive reprocessor.
        content_type = (
            "ARTICLE"
            if "feishu.cn/docx/" in (lesson.url or "")
            or (lesson.url or "").startswith("public://")
            else self.evaluate_learning_content_eligibility(lesson.content)
        )
        if content_type in {"INTERACTIVE_INDEX", "NAVIGATION_PAGE", "LINK_HUB"}:
            raise RuntimeError("本页是课程导航或交互入口，没有足够正文用于生成知识点。")
        # Section headings are navigation structure, not teachable knowledge points.
        points = [
            point for point in repository.list_knowledge_points(lesson.id)
            if point.category != "Section"
        ]
        if (lesson.url or "").startswith("public://"):
            from app.services.public_curriculum import public_point_ids

            allowed_ids = public_point_ids(lesson.id)
            points = [point for point in points if point.id in allowed_ids]
            if not points:
                raise RuntimeError("本节公开教材知识点尚未准备好，请重新启动应用完成内容更新。")
        # All Feishu docx pages share the same virtualized/chrome-heavy DOM.
        # Parse their verified body before any generic or LLM extraction so a
        # short heading can never become an invalid knowledge-point field.
        if "feishu.cn/docx/" in (lesson.url or "") and not points:
            self._reprocess_feishu_lesson(db, lesson)
            points = [
                point for point in repository.list_knowledge_points(lesson.id)
                if point.category != "Section"
            ]
        if content_type == "INTERACTIVE_LESSON" and points and any(
            self._is_generic_filler(
                point.core_explanation or "", point.why_explanation or "",
                point.teaching_example or "", point.ai_pm_relevance or "", title=point.name
            ) for point in points
        ):
            self.reprocess_interactive_lesson(db, lesson.id)
            points = [point for point in repository.list_knowledge_points(lesson.id) if point.category != "Section"]
        if not (lesson.url or "").startswith("public://"):
            points = [
                point for point in points
                if not (
                    self._is_noise_title(point.name)
                    or (
                    self._is_generic_filler(
                        point.core_explanation or "", point.why_explanation or "",
                        point.teaching_example or "", point.ai_pm_relevance or "", title=point.name
                    )
                    and len(self._source_evidence(lesson.content, point.name)) < 80
                    )
                )
            ]
        if points:
            course_summary = self._course_summary(lesson, points)
            # Public release lessons are authored, curated curriculum. Keep
            # their stable knowledge-point identities and teaching text intact;
            # runtime compression can otherwise rewrite the public syllabus
            # when a learner merely starts a practice session.
            refresh_points = [] if (lesson.url or "").startswith("public://") else [
                point
                for point in points
                if (
                self._is_generic_filler(
                    point.core_explanation or "", point.why_explanation or "",
                    point.teaching_example or "", point.ai_pm_relevance or "", title=point.name
                )
                or
                not point.core_explanation
                or not point.why_explanation
                or not point.teaching_example
                or not point.ai_pm_relevance
                or not point.interview_requirements_json
                or point.interview_requirements_json == "[]"
                or teaching_content_policy.needs_refresh(
                    point, teaching_content_policy.length(lesson.content)
                )
                )
            ]
            if refresh_points:
                for point in refresh_points:
                    evidence_point = self._evidence_structured_point(
                        point.name, self._source_evidence(lesson.content, point.name)
                    )
                    if evidence_point:
                        point.core_explanation = evidence_point.core_explanation
                        point.why_explanation = evidence_point.why_explanation
                        point.teaching_example = evidence_point.teaching_example
                        point.ai_pm_relevance = evidence_point.ai_pm_relevance
                fallback_items = [
                    CompactTeachingItem(
                        name=point.name,
                        core_explanation=self._minimum_teaching_text(
                            point.core_explanation or point.level_1 or point.description,
                            f"“{point.name}”需要从它的成因、过程和结果来理解，不能只记住结论。",
                        ),
                        why_explanation=self._minimum_teaching_text(
                            point.why_explanation or point.description,
                            f"理解“{point.name}”有助于判断它在产品中的价值、限制和适用边界。",
                        ),
                        teaching_example=self._minimum_teaching_text(
                            point.teaching_example or point.description,
                            f"例如在“{point.name}”相关场景中，先观察输入，再核对处理过程和输出结果。",
                        ),
                        ai_pm_relevance=self._minimum_teaching_text(
                            point.ai_pm_relevance or point.description,
                            f"AI 产品经理需要据此判断“{point.name}”的用户价值、验收指标、成本和风险。",
                        ),
                        extended_explanation=point.extended_explanation or "\n\n".join(
                            value
                            for value in (
                                point.core_explanation,
                                point.why_explanation,
                                point.teaching_example,
                                point.ai_pm_relevance,
                            )
                            if value
                        )[:4000],
                        interview_depth=normalized_interview_profile(
                            point.name, point.interview_depth, point.interview_value
                        )[0],
                        interview_value=normalized_interview_profile(
                            point.name, point.interview_depth, point.interview_value
                        )[1],
                        interview_requirements=[
                            "能解释是什么、为什么和核心机制",
                            "能说明使用场景、选型依据、基本指标与风险",
                        ],
                        unnecessary_detail=["数学推导", "算法证明", "具体代码实现"],
                    )
                    for point in refresh_points
                ]
                compact = await llm_service.complete_structured(
                    CompactTeachingBatchOutput,
                    tutor_system(
                        "只压缩已有知识点的教学正文，绝对不要改变知识点名称或拆分结构。"
                        "默认层使用最小充分解释：A核心解释80至160字、最多220字，只保留定义、2至3个机制和必要限制；"
                        "B为什么50至120字，只讲重要性；C只给一个60至120字具体例子；"
                        "D用50至120字说明影响哪些AI PM产品决策、指标、成本或风险。"
                        "A/B/C/D合计通常250至450字、绝不超过600字，避免相互复述。"
                        "删除趋势套话、营销表述和相似场景。extended_explanation保存被压缩掉的技术细节，"
                        "供用户按需展开。面试需要会2至4条，通常不需要1至3条。"
                    ),
                    f"知识点与当前正文：{json.dumps([{'name': p.name, 'description': p.description, 'core_explanation': p.core_explanation, 'why_explanation': p.why_explanation, 'teaching_example': p.teaching_example, 'ai_pm_relevance': p.ai_pm_relevance} for p in refresh_points], ensure_ascii=False)}"
                    f"\n课程原文（仅作证据，不要逐句覆盖）：{lesson.content}",
                    fallback=lambda: CompactTeachingBatchOutput(items=fallback_items),
                    max_tokens=3000,
                )
                generated = {item.name: item for item in compact.items}
                complete_items = [generated.get(item.name, item) for item in fallback_items]
                for teaching_item in complete_items:
                    self._normalize_point_metadata(teaching_item)
                    teaching_item.core_explanation = self._ensure_complete_content(teaching_item.core_explanation)
                    teaching_item.why_explanation = self._ensure_complete_content(teaching_item.why_explanation)
                    teaching_item.teaching_example = self._ensure_complete_content(teaching_item.teaching_example)
                    teaching_item.ai_pm_relevance = self._ensure_complete_content(teaching_item.ai_pm_relevance)
                    teaching_content_policy.enforce(teaching_item, lesson.content)
                points = [
                    point
                    for point in repository.update_compact_teaching(lesson.id, complete_items)
                    if point.category != "Section" and not self._is_noise_title(point.name)
                ]
        else:
            extraction = await llm_service.complete_structured(
                KnowledgeExtractionOutput,
                tutor_system(
                    "把页面拆成3至8个可独立考核的知识点。每个知识点默认只生成：核心解释、为什么、"
                    "一个具体教学例子、AI PM关联。四部分合计约250至450中文字、绝不超过600字。核心解释用2至4句"
                    "说明是什么和为什么，禁止只给结论；不得默认生成公式推导、知识树或完整面试答案。"
                    "A最多220字，B/C/D各最多120字，四部分不得机械重复。删除宏观趋势和营销套话。"
                    "被省略的技术细节放入extended_explanation，默认层不追求逐句覆盖。"
                    "同时标注interview_depth、1至5星interview_value、面试必会内容和普通AI PM"
                    "不需要掌握的细节。默认优先P1，只有纯数学推导、证明或实现类知识点才标P3。"
                ),
                    f"页面标题：{lesson.title}\n页面URL：{lesson.url}\n课程正文：\n{lesson.content}",
                fallback=lambda: (
                    self._fallback_pdf_extraction(lesson.content)
                    if lesson.source_type == "PDF"
                    else self._fallback_extraction(lesson.title, lesson.content)
                ),
                max_tokens=3500,
            )
            extraction.knowledge_points = [
                point for point in extraction.knowledge_points
                if not self._is_noise_title(point.name)
            ]
            if lesson.source_type == "PDF":
                extraction.knowledge_points = self._filter_pdf_points(extraction.knowledge_points)
                if not extraction.knowledge_points:
                    extraction = self._fallback_pdf_extraction(lesson.content)
                    extraction.knowledge_points = self._filter_pdf_points(extraction.knowledge_points)
                    if not extraction.knowledge_points:
                        raise RuntimeError("CONTENT_GENERATION_FAILED：PDF 内容未形成完整可学习主题。")
            course_summary = self._course_summary(lesson, extraction.knowledge_points)
            structural_titles = self._structural_heading_titles(lesson.content)
            if lesson.source_type != "PDF" and len(structural_titles) >= 3 and len(extraction.knowledge_points) <= 1:
                evidence_points = [
                    point
                    for title in structural_titles[:20]
                    if (point := self._evidence_structured_point(title, self._source_evidence(lesson.content, title))) is not None
                ]
                if evidence_points:
                    extraction.knowledge_points = evidence_points
            if False and lesson.source_type != "PDF" and len(structural_titles) >= 3 and len(extraction.knowledge_points) <= 1:
                # A long structured GitBook page must not degrade to one giant KP.
                extraction.knowledge_points = [
                    ExtractedKnowledgePoint(
                        name=title[:80], description=f"本节聚焦{title}的核心概念与应用边界。",
                        category="课程章节", difficulty="基础", importance_for_ai_pm=3,
                        importance_for_interview=3, prerequisite="", core_explanation=f"{title}是本页的独立学习主题，需理解其定义、关键机制和产品影响。",
                        why_explanation=f"理解{title}有助于建立完整的技术与产品判断。",
                        teaching_example=f"在实际AI产品中，可围绕{title}设计一个小场景并观察输入、处理与结果。",
                        ai_pm_relevance="AI产品经理需要据此判断方案价值、效果指标与落地风险。",
                        interview_requirements=["能解释核心概念", "能结合产品场景"], unnecessary_detail=[]
                    ) for title in structural_titles[:20]
                ]
            for extracted_point in extraction.knowledge_points:
                self._normalize_point_metadata(extracted_point)
                extracted_point.core_explanation = self._ensure_complete_content(extracted_point.core_explanation)
                extracted_point.why_explanation = self._ensure_complete_content(extracted_point.why_explanation)
                extracted_point.teaching_example = self._ensure_complete_content(extracted_point.teaching_example)
                extracted_point.ai_pm_relevance = self._ensure_complete_content(extracted_point.ai_pm_relevance)
                teaching_content_policy.enforce(extracted_point, lesson.content)
            points = repository.replace_knowledge_points(lesson, extraction.knowledge_points)
        interview_candidates = [
            point
            for point in points
            if point.interview_depth != "P3"
            and not (
                target_role_service.point_readiness(repository, point, profile)[1]
            )
        ]
        current_candidates = interview_candidates or [
            point for point in points if point.interview_depth != "P3"
        ] or points
        current = max(
            current_candidates,
            key=lambda point: (self._point_priority(repository, point, profile), -point.id),
        )
        for point in points:
            point.source_course_id = lesson.course_id
            point.source_section_id = lesson.section_title or lesson.chapter_title or ""
            point.source_kp_id = point.id
            point.source_page_start = lesson.source_page_start
            point.source_page_end = lesson.source_page_end
            point.source_evidence_json = json.dumps([{
                "source_course_id": lesson.course_id,
                "source_section_id": point.source_section_id,
                "source_kp_id": point.id,
                "source_page_start": lesson.source_page_start,
                "source_page_end": lesson.source_page_end,
                "source_text": (
                    self._source_evidence(lesson.content or "", point.name)
                    or point.description
                    or point.core_explanation
                    or ""
                )[:1200],
            }], ensure_ascii=False)
        db.commit()
        session = repository.create_learning_session(
            lesson.id, current.id, course_summary, profile.id,
            **({k: v for k, v in scope.items() if k != "label"} if scope else {})
        )
        question = await self._generate_question(repository, current, 1, "initial", profile_override=profile)
        await coverage_service.prepare(db, current, question.question)
        attempt = repository.create_question_attempt(session.id, current.id, question, "initial")
        return {
            "session_id": session.id,
            "lesson_title": lesson.title,
            "scope_label": scope["label"] if scope else "",
            "course_summary": course_summary,
            "page_mastery": repository.page_mastery(lesson.id),
            "page_interview_readiness": target_role_service.page_readiness(
                repository, lesson.id, profile
            ),
            "knowledge_points": [
                self._point_view(repository, point, profile) for point in points
            ],
            "current_knowledge_point": self._point_view(repository, current, profile),
            "question_attempt_id": attempt.id,
            "question": question.model_dump(),
        }

    async def start_learning_unit(self, db: Session, unit_id: int) -> dict:
        """Start a goal unit in the existing mastery loop using only referenced source points."""
        repository = Repository(db)
        unit = db.get(LearningUnit, unit_id)
        if not unit:
            raise LookupError("学习单元不存在。")
        try:
            point_ids = json.loads(unit.source_knowledge_point_ids_json or "[]")
        except (TypeError, json.JSONDecodeError):
            point_ids = []
        points = list(db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(point_ids)).all()) if point_ids else []
        if not points:
            raise LookupError("该学习单元已没有可学习的来源知识点。")
        primary = next((point for point in points if point.id == unit.primary_knowledge_point_id), points[0])
        lesson = repository.get_lesson(primary.lesson_id)
        if not lesson:
            raise LookupError("学习单元的来源章节已不存在。")
        goal = db.get(LearningGoal, unit.goal_id)
        profile = PROFILES.get(goal.target_role) if goal else None
        profile = profile or target_role_service.selected_profile(repository)
        active_session = db.scalar(
            select(LearningSession)
            .where(LearningSession.learning_unit_id == unit.id, LearningSession.completed.is_(False))
            .order_by(LearningSession.updated_at.desc(), LearningSession.id.desc())
            .limit(1)
        )
        if active_session:
            pending_attempt = db.scalar(
                select(QuestionAttempt)
                .where(
                    QuestionAttempt.learning_session_id == active_session.id,
                    QuestionAttempt.user_answer == "",
                )
                .order_by(QuestionAttempt.created_at.desc(), QuestionAttempt.id.desc())
                .limit(1)
            )
            if pending_attempt:
                current_point = repository.get_knowledge_point(active_session.current_knowledge_point_id)
                if current_point:
                    try:
                        question_fingerprint = json.loads(pending_attempt.question_fingerprint_json or "{}")
                    except (TypeError, json.JSONDecodeError):
                        question_fingerprint = {}
                    question = {
                        "question_type": pending_attempt.question_type,
                        "difficulty": pending_attempt.difficulty,
                        "question": pending_attempt.question,
                        "assessment_focus": json.loads(pending_attempt.assessment_focus_json or "[]"),
                        "interview_category": pending_attempt.interview_category,
                        "target_role": pending_attempt.target_role,
                        "interview_value": pending_attempt.interview_value,
                        "interview_depth": pending_attempt.interview_depth,
                        "why_interviewer_asks": pending_attempt.why_interviewer_asks,
                        "must_have_points": json.loads(pending_attempt.must_have_points_json or "[]"),
                        "bonus_points": json.loads(pending_attempt.bonus_points_json or "[]"),
                        "unnecessary_detail": pending_attempt.unnecessary_detail,
                        "question_fingerprint": question_fingerprint,
                    }
                    return {
                        "session_id": active_session.id,
                        "lesson_title": unit.title,
                        "scope_label": "学习目标路径 · 继续学习",
                        "course_summary": active_session.course_summary,
                        "page_mastery": repository.page_mastery(lesson.id),
                        "page_interview_readiness": target_role_service.page_readiness(repository, lesson.id, profile),
                        "knowledge_points": [self._point_view(repository, point, profile) for point in points],
                        "current_knowledge_point": self._point_view(repository, current_point, profile),
                        "question_attempt_id": pending_attempt.id,
                        "question": question,
                    }

        candidates = [point for point in points if point.interview_depth != "P3"] or points
        current = max(candidates, key=lambda point: (self._point_priority(repository, point, profile), -point.id))
        session = repository.create_learning_session(
            lesson.id, current.id, f"{unit.title} · {len(points)} 个来源知识点", profile.id,
            scope_type="UNIT", learning_unit_id=unit.id, knowledge_point_ids=[point.id for point in points],
        )
        question = await self._generate_question(repository, current, 1, "initial", profile_override=profile)
        await coverage_service.prepare(db, current, question.question)
        attempt = repository.create_question_attempt(session.id, current.id, question, "initial")
        unit.status = "IN_PROGRESS"
        db.commit()
        return {
            "session_id": session.id, "lesson_title": unit.title, "scope_label": "学习目标路径",
            "course_summary": session.course_summary, "page_mastery": repository.page_mastery(lesson.id),
            "page_interview_readiness": target_role_service.page_readiness(repository, lesson.id, profile),
            "knowledge_points": [self._point_view(repository, point, profile) for point in points],
            "current_knowledge_point": self._point_view(repository, current, profile),
            "question_attempt_id": attempt.id, "question": question.model_dump(),
        }

    @staticmethod
    def _session_knowledge_points(repository: Repository, session) -> list[KnowledgePoint]:
        try:
            ids = json.loads(session.knowledge_point_ids_json or "[]")
        except (TypeError, json.JSONDecodeError):
            ids = []
        if ids:
            points = list(repository.db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(ids)).all())
            return sorted(points, key=lambda point: ids.index(point.id))
        return repository.list_knowledge_points(session.lesson_id)

    @staticmethod
    def _session_profile(repository: Repository, session):
        lesson = repository.db.get(Lesson, session.lesson_id)
        if session.learning_unit_id or (lesson and (lesson.url or '').startswith('public://')):
            profile = PROFILES.get(session.target_role)
            if profile:
                return profile
        return target_role_service.selected_profile(repository)

    @staticmethod
    def _compact_answer(text: str, fallback: str = "") -> str:
        value = (text or "").strip()
        for prefix in ("建议你：", "你的回答：", "可以补充：", "建议："):
            if value.startswith(prefix):
                value = value[len(prefix):].lstrip()
        if not value:
            value = fallback.strip()
        if len(value) <= 300:
            return value
        clipped = value[:300]
        boundary = max(clipped.rfind("。"), clipped.rfind("；"), clipped.rfind("！"), clipped.rfind("？"))
        return clipped[:boundary + 1] if boundary >= 180 else clipped.rstrip("，、；：") + "。"

    @staticmethod
    def _calibrate_evaluation(result: AnswerEvaluationOutput, attempt, answer: str) -> AnswerEvaluationOutput:
        """Guard against a good answer being failed by an inconsistent LLM score."""
        text = answer.strip()
        must = [item for item in (attempt.must_have_points_json or "").replace("[", "").replace("]", "").replace('"', "").split(",") if item.strip()]
        covered = sum(1 for item in must if item.strip() and item.strip() in text)
        ref = result.expert_answer or ""
        grams = lambda value: {value[i:i + 2] for i in range(max(0, len(value) - 1)) if value[i:i + 2].strip()}
        ref_grams, answer_grams = grams(ref), grams(text)
        similarity = len(ref_grams & answer_grams) / max(1, len(ref_grams | answer_grams))
        if result.total_score < 60 and not result.critical_misconception and (covered >= max(1, len(must) * 0.6) or similarity >= 0.32) and len(text) >= 45:
            result.concept_accuracy = max(result.concept_accuracy, 17)
            result.technical_understanding = max(result.technical_understanding, 16)
            result.product_thinking = max(result.product_thinking, 16)
            result.application_scenario = max(result.application_scenario, 12)
            result.communication_structure = max(result.communication_structure, 9)
            result.correct_points = list(dict.fromkeys([*result.correct_points, "覆盖了题目核心判断"]))
        if result.total_score >= 60 and not result.critical_misconception:
            result.weaknesses = [w for w in result.weaknesses if w.weakness_type and w.weakness_type not in {"核心机制说明不完整", "结构化说明仍不充分"}]
        return result

    @staticmethod
    def _fallback_evaluation(point, attempt, answer: str) -> AnswerEvaluationOutput:
        from app.services.public_practice import reference_guide
        guide = reference_guide(point, attempt)
        return AnswerEvaluationOutput(
            evaluation_source='offline',
            concept_accuracy=0, technical_understanding=0, product_thinking=0,
            application_scenario=0, communication_structure=0,
            correct_points=[], missing_points=[],
            incorrect_points=[],
            imprecise_expressions=[], interviewer_followups=[],
            improved_answer='', expert_answer=guide['answer'] if guide else '',
            answer_framework=guide['framework'] if guide else [], weaknesses=[],
            critical_misconception=False,
            weak_concepts=[], weak_reasoning=[], weak_product_application=[],
            review_later=[],
            next_action="remediate",
            answer_level="可用",
            score_explanation="尚未完成模型评价，不能据此判断得分、缺口或是否达到面试要求。答案已保存，可检查模型连接后重新评价。",
            next_level_gap='',
        )

    async def _evaluate_answer(self, point, attempt, answer: str) -> AnswerEvaluationOutput:
        from app.services.public_practice import reference_guide
        guide = reference_guide(point, attempt)
        used_fallback = False

        def fallback():
            nonlocal used_fallback
            used_fallback = True
            return self._fallback_evaluation(point, attempt, answer)

        result = await llm_service.complete_structured(
            AnswerEvaluationOutput,
            tutor_system(
                "只能依据给定教学内容严格、可追溯地评价。重点检查：结论是否正确、是否解释原因、"
                "是否形成因果链、能否结合例子、能否说出AI PM意义。五个维度各20分。用户只遗漏"
                "部分原因时，只指出并补充遗漏，不要重新教学整个知识点。严格按must_have_points"
                "评分；unnecessary_detail明确列出的内容不会，不得影响普通AI PM面试评分。"
                "Improved Answer保留用户思路。只有会导致核心结论或产品判断方向错误的误解，才标记"
                "critical_misconception=true。若总分达到60且没有关键误解，把非关键遗漏写入review_later，"
                "不得因此判失败。Improved Answer和Expert Answer必须是可直接用于面试的完整改写答案，"
                "每个不超过300个中文字符；不得写点评、建议或‘你的回答/建议你/可以补充’等反馈措辞，"
                "保留正确观点并补上1至2个关键遗漏，形成结论、因果分析和产品判断。"
                "额外输出answer_level（未达标/可用/较好/优秀）、score_explanation和next_level_gap，"
                "明确区分60分可用与80分较好的差异：当前回答已做到什么、缺少什么证据、提升到下一级最关键的一步。"
                "同时输出answer_framework与key_gaps：框架须结合本题、rubric和expert_answer，提炼4至6个有因果/决策顺序的短步骤，整体约80至150个中文字符，只给逻辑骨架，不新增rubric之外的要求；按题型组织，禁止套用通用模板。"
                "key_gaps最多3项，按影响排序，每项包含point、why_it_matters、direction；direction只给补充方向，不可代答整题。"
                "评价只对应当前问题，不得混入同课的首问题或下一道补测题。先逐项核查用户是否已表达必答点，接受同义、合理替代方案；"
                "correct_points须具体对应用户已表达的内容，key_gaps只指出确实未覆盖且本题要求的内容。禁止用笼统的‘核心原理/产品权衡’否定已有答案。"
                "不按字数评分，不因没有复述标准答案而扣分。优化答案应是可直接口述的连贯回答，不能把用户原话与课文拼接，也不能带批改口吻。"
            ),
            f"{self._point_context(point)}\n题型：{attempt.question_type}\n难度：{attempt.difficulty}"
            f"\n面试深度：{attempt.interview_depth}\n面试官为什么问：{attempt.why_interviewer_asks}"
            f"\n必答点：{attempt.must_have_points_json}\n加分点：{attempt.bonus_points_json}"
            f"\n不必要细节：{attempt.unnecessary_detail}\n考察重点：{attempt.assessment_focus_json}"
            f"\n问题：{attempt.question}\n用户答案：{answer}"
            f"\n本题原创参考（不是唯一正确表达）：{json.dumps(guide, ensure_ascii=False) if guide else '按当前题目与必答点评价，不套用其他题的答案。'}",
            # The original case guide is context, not a keyword-matching answer key.
            fallback=fallback,
        )
        result.evaluation_source = 'offline' if used_fallback else 'model'
        if used_fallback and getattr(llm_service, '_configured', None) is False:
            result.score_explanation = (
                '公开版尚未配置评分模型。本次只保存回答、不计分，也不改变掌握度。'
                '请打开页面顶部的“模型设置”，填入你自己的配置，再点击重新评价；无需重启。'
            )
        elif used_fallback and getattr(llm_service, 'last_error', ''):
            result.score_explanation = (
                f'{llm_service.last_error} 本次只保存回答、不计分；请在“模型设置”核对配置后重新评价。'
            )
        return result

    @staticmethod
    def _fallback_remediation(point, weaknesses: list) -> RemediationOutput:
        weakness_names = "、".join(item.weakness_type for item in weaknesses[:3])
        return RemediationOutput(
            mini_lesson=point.core_explanation or point.level_1,
            example=point.teaching_example,
            contrast=f"重点区分：已经掌握的定义，与尚未说清的{weakness_names or '核心机制'}。",
            retest_question=StudyService._fallback_question(point, 2, "retest"),
        )

    async def _build_remediation(self, point, weaknesses: list) -> RemediationOutput:
        weakness_data = [
            {"type": item.weakness_type, "evidence": item.evidence, "severity": item.severity}
            for item in weaknesses
        ]
        return await llm_service.complete_structured(
            RemediationOutput,
            tutor_system(
                "只补用户遗漏的部分，不要重新讲完整知识点。若是部分正确，用简短因果链补缺失点；"
                "若明显不理解，给更简单解释和一个新例子。最后只生成1道全新重测题。"
            ),
            f"{self._point_context(point)}\n薄弱点：{json.dumps(weakness_data, ensure_ascii=False)}",
            fallback=lambda: self._fallback_remediation(point, weaknesses),
        )

    async def answer_mastery_question(
        self, db: Session, session_id: int, attempt_id: int, answer: str
    ) -> dict:
        repository = Repository(db)
        old_readiness = interview_priority_service.dashboard(repository)["interview_readiness"]
        session = repository.get_learning_session(session_id)
        attempt = repository.get_question_attempt(attempt_id)
        if not session or not attempt or attempt.learning_session_id != session.id:
            raise LookupError("学习会话或题目不存在。")
        profile = self._session_profile(repository, session)
        if attempt.user_answer and db.query(AnswerEvaluation).filter_by(question_attempt_id=attempt.id).first():
            raise ValueError("这道题已经提交过，请继续下一步。")
        point = repository.get_knowledge_point(attempt.knowledge_point_id)
        if not point:
            raise LookupError("关联知识点不存在。")
        repository.update_learning_session(session, target_role=profile.id)
        repository.answer_question_attempt(attempt, answer)
        result = await self._evaluate_answer(point, attempt, answer)
        is_public = (point.source_url or '').startswith('public://')
        if is_public and result.evaluation_source == 'offline':
            # Save the user's answer, but never turn a provider outage into a failed
            # evaluation, weakness, retest, review entry or mastery-score update.
            mastery = repository.get_mastery_score(point.id)
            readiness, ready = target_role_service.point_readiness(repository, point, profile)
            return {
                'evaluation_source': 'offline', 'evaluated_question': attempt.question,
                'attempt_id': attempt.id, 'total_score': None, 'dimensions': None,
                'answer_level': '待评价', 'score_explanation': result.score_explanation,
                'next_level_gap': '', 'correct_points': [], 'missing_points': [],
                'incorrect_points': [], 'imprecise_expressions': [], 'interviewer_followups': [],
                'user_answer': answer, 'improved_answer': '', 'expert_answer': result.expert_answer,
                'answer_framework': result.answer_framework, 'key_gaps': [], 'weaknesses': [],
                'mastery_score': mastery.mastery_score if mastery else 0,
                'mastery_status': mastery.status if mastery else '未学习',
                'interview_readiness': readiness, 'interview_ready': ready,
                'interview_message': '本次尚未评价，原有学习进度保持不变。',
                'old_readiness': old_readiness, 'new_readiness': old_readiness, 'readiness_delta': 0,
                'pass_status': 'UNASSESSED', 'pass_label': '尚未完成评价',
                'critical_misconception': False, 'critical_misconception_detail': '',
                'review_later': [],
                'mastery_breakdown': {
                    name: getattr(mastery, name, 0) if mastery else 0
                    for name in ('knowledge_coverage', 'assessment_score', 'transfer_score', 'review_stability')
                },
                'page_mastery': repository.page_mastery(session.lesson_id),
                'page_interview_readiness': target_role_service.page_readiness(repository, session.lesson_id, profile),
                'next_action': 'retry_evaluation', 'next_question': None, 'next_attempt_id': None,
            }
        if not is_public:
            result = self._calibrate_evaluation(result, attempt, answer)
        from app.services.public_practice import reference_guide
        guide = reference_guide(point, attempt)
        result.improved_answer = self._compact_answer(
            result.improved_answer,
            guide['answer'] if guide else '本次未生成可靠的优化答案，请按当前题目要求核对必答点。',
        )
        result.expert_answer = self._compact_answer(
            result.expert_answer,
            guide['answer'] if guide else '',
        )
        rubric = {
            "must_have_points": json.loads(attempt.must_have_points_json or "[]"),
            "assessment_focus": json.loads(attempt.assessment_focus_json or "[]"),
            "bonus_points": json.loads(attempt.bonus_points_json or "[]"),
        }
        result.answer_framework, framework_status = generate_answer_framework(
            attempt.question, rubric, answer, result.expert_answer, result.answer_framework
        )
        result.key_gaps = [
            AnswerKeyGap(**item)
            for item in prioritized_key_gaps(
                [gap.model_dump() for gap in result.key_gaps],
                result.missing_points,
                rubric["must_have_points"],
            )
        ]
        passed = result.total_score >= 60 and not result.critical_misconception
        if passed and not result.review_later:
            result.review_later = [
                *result.missing_points,
                *result.imprecise_expressions,
            ][:8]
        evaluation_record = repository.save_answer_evaluation(
            attempt, result, framework_version=FRAMEWORK_VERSION
        )
        # Keep one deduplicated entry in the unified mistake book. Mastered
        # retries update the same row instead of creating another card.
        repository.upsert_mistake(attempt=attempt, evaluation=evaluation_record, source_type="SMART_LEARNING")
        repository.add_review_history(attempt, result.total_score)
        mastery = mastery_calculator.update(repository, point.id)
        new_readiness = interview_priority_service.dashboard(repository)["interview_readiness"]
        role_readiness, role_ready = target_role_service.point_readiness(
            repository, point, profile
        )
        weakness_records = []
        if not passed:
            findings = result.weaknesses or [
                WeaknessFinding(
                    weakness_type=f"{point.name}的关键内容存在遗漏",
                    evidence="；".join(result.missing_points) or answer[:300],
                    severity="high" if result.critical_misconception else "medium",
                )
            ]
            weakness_records = [
                repository.upsert_weakness(
                    point.id,
                    item.weakness_type,
                    item.evidence,
                    item.severity,
                    mastery.mastery_score,
                )
                for item in findings
            ]
        elif result.total_score >= 85:
            repository.resolve_weaknesses(point.id, mastery.mastery_score)

        mastery = mastery_calculator.update(repository, point.id)

        attempts = repository.attempts_with_scores(point.id)
        remediation = None
        next_attempt = None
        next_question = None
        evaluated_attempts = repository.attempts_with_evaluations(point.id)
        consecutive_failures = 0
        for previous_attempt, evaluation in reversed(evaluated_attempts):
            if previous_attempt.interview_depth == "P3":
                continue
            if evaluation.total_score >= 60 and not evaluation.critical_misconception:
                break
            consecutive_failures += 1
        previous_angle = question_diversity_service.attempt_fingerprint(
            attempt
        ).reasoning_target
        retest_message = ""
        current_angle = ""
        pass_status = "PASS" if passed else "LEARNING"
        if passed:
            next_action = "interview_ready"
            repository.update_learning_session(session, mode="advance", increment_answers=True)
        elif consecutive_failures < 2:
            next_action = "probe"
            angle = question_diversity_service.targeted_angle(consecutive_failures, result)
            next_question = await self._generate_question(
                repository,
                point,
                min(3, consecutive_failures + 1),
                "targeted",
                attempts,
                forced_category="AI技术理解",
                targeted_angle=angle,
                profile_override=profile,
            )
            await coverage_service.prepare(db, point, next_question.question)
            next_attempt = repository.create_question_attempt(
                session.id, point.id, next_question, "targeted"
            )
            current_angle = next_question.question_fingerprint.reasoning_target
            retest_message = "这次换一个角度，专门验证刚才遗漏的部分。"
            repository.update_learning_session(session, mode="question", increment_answers=True)
        elif consecutive_failures == 2:
            next_action = "defer_and_continue"
            pass_status = "DEFERRED_REVIEW"
            retest_message = "这个知识点今天先暂停，避免重复消耗时间。系统会将它加入明日优先复习，且不会计入当前学习进度。"
            repository.update_learning_session(session, mode="advance", increment_answers=False)
        elif consecutive_failures == 3:
            next_action = "remediate"
            remediation = await self._build_remediation(point, weakness_records)
            angle = question_diversity_service.targeted_angle(consecutive_failures, result)
            next_question = await self._generate_question(
                repository,
                point,
                2,
                "remediation_validation",
                attempts,
                forced_category="AI技术理解",
                forced_depth="P1",
                targeted_angle=angle,
                profile_override=profile,
            )
            await coverage_service.prepare(db, point, next_question.question)
            remediation.retest_question = next_question
            next_attempt = repository.create_question_attempt(
                session.id, point.id, next_question, "remediation_validation"
            )
            current_angle = next_question.question_fingerprint.reasoning_target
            retest_message = f"你目前主要卡在：{'、'.join(result.weak_concepts or result.missing_points[:3])}。"
            repository.update_learning_session(session, mode="remediation", increment_answers=True)
        else:
            next_action = "needs_review"
            pass_status = "NEEDS_REVIEW"
            remediation = await self._build_remediation(point, weakness_records)
            angle = question_diversity_service.targeted_angle(consecutive_failures, result)
            next_question = await self._generate_question(
                repository,
                point,
                2,
                "voluntary_remediation",
                attempts,
                forced_category="AI技术理解",
                forced_depth="P1",
                targeted_angle=angle,
                profile_override=profile,
            )
            await coverage_service.prepare(db, point, next_question.question)
            remediation.retest_question = next_question
            next_attempt = repository.create_question_attempt(
                session.id, point.id, next_question, "voluntary_remediation"
            )
            current_angle = next_question.question_fingerprint.reasoning_target
            retest_message = "多次补测仍未达到60分，已标记为稍后复习。你可以继续补强，也可以暂时跳过。"
            repository.update_learning_session(session, mode="advance", increment_answers=True)
            repository.set_interview_status(point.id, "NEEDS_REVIEW")
        if passed:
            pass_label = (
                "已达到基础面试要求"
                if result.total_score < 70
                else "掌握良好"
                if result.total_score < 85
                else "掌握较强，可应对深入追问"
            )
        elif pass_status == "NEEDS_REVIEW":
            pass_label = "需要稍后复习"
        else:
            pass_label = "尚未达到基础面试要求"
        return {
            'evaluation_source': result.evaluation_source,
            'evaluated_question': attempt.question,
            "attempt_id": attempt.id,
            "old_readiness": old_readiness,
            "new_readiness": new_readiness,
            "readiness_delta": new_readiness - old_readiness,
            "total_score": result.total_score,
            "dimensions": {
                "concept_accuracy": result.concept_accuracy,
                "technical_understanding": result.technical_understanding,
                "product_thinking": result.product_thinking,
                "application_scenario": result.application_scenario,
                "communication_structure": result.communication_structure,
            },
            "correct_points": result.correct_points,
            "missing_points": result.missing_points,
            "incorrect_points": result.incorrect_points,
            "imprecise_expressions": result.imprecise_expressions,
            "interviewer_followups": result.interviewer_followups,
            "user_answer": answer,
            "improved_answer": result.improved_answer,
            "expert_answer": result.expert_answer,
            "answer_level": result.answer_level,
            "score_explanation": result.score_explanation,
            "next_level_gap": result.next_level_gap,
            "answer_framework": result.answer_framework,
            "framework_version": FRAMEWORK_VERSION,
            "framework_generation_status": framework_status,
            "key_gaps": [item.model_dump() for item in result.key_gaps],
            "weaknesses": [
                {
                    "id": item.id,
                    "knowledge_point_id": item.knowledge_point_id,
                    "weakness_type": item.weakness_type,
                    "evidence": item.evidence,
                    "severity": item.severity,
                    "mistake_count": item.mistake_count,
                    "current_mastery": item.current_mastery,
                }
                for item in weakness_records
            ],
            "mastery_score": mastery.mastery_score,
            "mastery_status": mastery.status,
            "interview_readiness": role_readiness,
            "interview_ready": role_ready,
            "interview_message": (
                f"已达到{profile.name}的基础面试要求，可以继续下一知识点。"
                if passed
                else retest_message
            ),
            "pass_status": pass_status,
            "pass_label": pass_label,
            "critical_misconception": result.critical_misconception,
            "critical_misconception_detail": result.critical_misconception_detail,
            "review_later": result.review_later,
            "retest_message": retest_message,
            "previous_question_angle": previous_angle,
            "current_question_angle": current_angle,
            "mastery_breakdown": {
                "knowledge_coverage": mastery.knowledge_coverage,
                "assessment_score": mastery.assessment_score,
                "transfer_score": mastery.transfer_score,
                "review_stability": mastery.review_stability,
            },
            "page_mastery": repository.page_mastery(session.lesson_id),
            "page_interview_readiness": target_role_service.page_readiness(
                repository, session.lesson_id, profile
            ),
            "next_action": next_action,
            "remediation": remediation.model_dump() if remediation else None,
            "next_attempt_id": next_attempt.id if next_attempt else None,
            "next_question": next_question.model_dump() if next_question else None,
        }

    async def continue_mastery_loop(self, db: Session, session_id: int) -> dict:
        repository = Repository(db)
        session = repository.get_learning_session(session_id)
        if not session:
            raise LookupError("学习会话不存在。")
        profile = self._session_profile(repository, session)
        if session.mode != "advance":
            raise ValueError("当前知识点尚未达到进入下一知识点的条件。")
        points = self._session_knowledge_points(repository, session)
        candidates = [
            point
            for point in points
            if point.id != session.current_knowledge_point_id
            and point.interview_depth != "P3"
            and not (
                target_role_service.point_readiness(repository, point, profile)[1]
            )
        ]
        if not candidates:
            repository.update_learning_session(session, mode="complete", completed=True)
            if session.learning_unit_id:
                unit = db.get(LearningUnit, session.learning_unit_id)
                if unit:
                    unit.status = "COMPLETED"
                    db.commit()
            return {"completed": True}
        point = max(
            candidates,
            key=lambda item: (self._point_priority(repository, item, profile), -item.id),
        )
        question = await self._generate_question(repository, point, 1, "initial", profile_override=profile)
        await coverage_service.prepare(db, point, question.question)
        attempt = repository.create_question_attempt(session.id, point.id, question, "initial")
        repository.update_learning_session(
            session,
            mode="question",
            knowledge_point_id=point.id,
            target_role=profile.id,
        )
        return {
            "completed": False,
            "current_knowledge_point": self._point_view(repository, point, profile),
            "question_attempt_id": attempt.id,
            "question": question.model_dump(),
        }

    async def switch_mastery_knowledge_point(
        self, db: Session, session_id: int, knowledge_point_id: int
    ) -> dict:
        repository = Repository(db)
        session = repository.get_learning_session(session_id)
        if not session:
            raise LookupError("学习会话不存在。")
        profile = self._session_profile(repository, session)
        point = repository.get_knowledge_point(knowledge_point_id)
        if not point or point.id not in {item.id for item in self._session_knowledge_points(repository, session)}:
            raise LookupError("知识点不属于当前课程页面。")
        attempts = repository.attempts_with_scores(point.id)
        latest_score = attempts[-1][1] if attempts else 0
        difficulty = 3 if latest_score >= 85 else 2 if latest_score >= 70 else 1
        question = await self._generate_question(
            repository, point, difficulty, "switch", attempts, profile_override=profile
        )
        await coverage_service.prepare(db, point, question.question)
        attempt = repository.create_question_attempt(
            session.id, point.id, question, "switch"
        )
        repository.update_learning_session(
            session,
            mode="question",
            knowledge_point_id=point.id,
            completed=False,
            target_role=profile.id,
        )
        return {
            "completed": False,
            "current_knowledge_point": self._point_view(repository, point, profile),
            "question_attempt_id": attempt.id,
            "question": question.model_dump(),
        }

    async def deepen_mastery_loop(self, db: Session, session_id: int) -> dict:
        repository = Repository(db)
        session = repository.get_learning_session(session_id)
        if not session:
            raise LookupError("学习会话不存在。")
        profile = self._session_profile(repository, session)
        point = repository.get_knowledge_point(session.current_knowledge_point_id)
        if not point:
            raise LookupError("当前知识点不存在。")
        attempts = repository.attempts_with_scores(point.id)
        question = await self._generate_question(
            repository,
            point,
            3,
            "deep_dive",
            attempts,
            forced_category="纯算法细节",
            forced_depth="P3",
            profile_override=profile,
        )
        await coverage_service.prepare(db, point, question.question)
        attempt = repository.create_question_attempt(
            session.id, point.id, question, "deep_dive"
        )
        repository.update_learning_session(
            session, mode="question", completed=False, target_role=profile.id
        )
        return {
            "completed": False,
            "current_knowledge_point": self._point_view(repository, point, profile),
            "question_attempt_id": attempt.id,
            "question": question.model_dump(),
        }

    def interview_dashboard(self, db: Session, course_id: int | None = None) -> dict:
        return interview_priority_service.dashboard(Repository(db), course_id)

    def create_interview_sprint(
        self,
        db: Session,
        preparation_days: int,
        daily_minutes: int,
        target_role: str,
        learning_goal: str = "INTERVIEW_SPRINT",
        target_interview_readiness: int = 60,
        replan: bool = False,
    ) -> dict:
        return interview_sprint_service.create(
            Repository(db),
            preparation_days=preparation_days,
            daily_minutes=daily_minutes,
            target_role=target_role,
            learning_goal=learning_goal,
            target_interview_readiness=target_interview_readiness,
            replan=replan,
        )

    def active_interview_sprint(self, db: Session) -> dict | None:
        return interview_sprint_service.active(Repository(db))

    def target_role_state(self, db: Session) -> dict:
        repository = Repository(db)
        selected = target_role_service.selected_profile(repository)
        return {
            "selected_role": selected.id,
            "selected_role_name": selected.name,
            "profiles": [
                {
                    "id": profile.id,
                    "name": profile.name,
                    "core_skills": profile.core_skills,
                    "interview_topic_weights": profile.interview_topic_weights,
                    "importance_topic_weights": profile.importance_topic_weights,
                    "technical_depth_requirement": profile.technical_depth_requirement,
                    "case_focus": profile.case_focus,
                    "project_focus": profile.project_focus,
                }
                for profile in PROFILES.values()
            ],
        }

    def update_target_role(self, db: Session, target_role: str) -> dict:
        if target_role not in PROFILES:
            raise ValueError("不支持的目标岗位。")
        repository = Repository(db)
        repository.set_target_role(target_role)
        importance_engine.recalculate(repository, repository.get_learning_goal(), target_role)
        return self.target_role_state(db)

    async def recalculate_role_view(self, db: Session, session_id: int) -> dict:
        repository = Repository(db)
        session = repository.get_learning_session(session_id)
        if not session:
            raise LookupError("学习会话不存在。")
        profile = target_role_service.selected_profile(repository)
        repository.update_learning_session(session, target_role=profile.id)
        points = self._session_knowledge_points(repository, session)
        current = repository.get_knowledge_point(session.current_knowledge_point_id)
        if not current:
            raise LookupError("当前知识点不存在。")
        current_readiness, current_ready = target_role_service.point_readiness(
            repository, current, profile
        )
        question = None
        attempt = None
        if not current_ready:
            attempts = repository.attempts_with_scores(current.id)
            question = await self._generate_question(
                repository,
                current,
                2 if current_readiness >= 80 else 1,
                "role_switch",
                attempts,
            )
            await coverage_service.prepare(db, current, question.question)
            attempt = repository.create_question_attempt(
                session.id, current.id, question, "role_switch"
            )
            repository.update_learning_session(session, mode="question")
        else:
            repository.update_learning_session(session, mode="advance")
        return {
            "page_interview_readiness": target_role_service.page_readiness(
                repository, session.lesson_id, profile
            ),
            "knowledge_points": [
                self._point_view(repository, point, profile) for point in points
            ],
            "current_knowledge_point": self._point_view(repository, current, profile),
            "question_attempt_id": attempt.id if attempt else None,
            "question": question.model_dump() if question else None,
        }

    async def expand_tutor_content(
        self,
        db: Session,
        session_id: int,
        knowledge_point_id: int,
        mode: str,
        compare_concept: str,
        previous_content: list[str],
    ) -> dict:
        repository = Repository(db)
        session = repository.get_learning_session(session_id)
        point = repository.get_knowledge_point(knowledge_point_id)
        if not session or not point or point.id not in {item.id for item in self._session_knowledge_points(repository, session)}:
            raise LookupError("学习会话或知识点不存在。")
        compare_concept = (compare_concept or "").strip()
        if mode == "compare" and not compare_concept:
            raise ValueError("请输入要对比的概念。")
        instructions = {
            "simpler": "用更简单的语言重讲。必须使用的陌生术语首次出现时用括号补一句解释。",
            "why": (
                "只解释当前核心结论的因果链，不要重新总结整个知识点。严格采用："
                "原因1 → 导致什么 → 最终结果。"
            ),
            "example": (
                "生成一个与默认例子和历史展开都不同的新例子。优先AI产品场景，其次日常场景，"
                "最后简单数字例子；明确输入、过程和输出。"
            ),
            "technical": (
                "只展开必要的技术细节：原理、输入输出、关键机制和适用边界。除非不可避免，"
                "不要长篇公式推导。"
            ),
            "compare": (
                f"与“{compare_concept}”对比，只比较定义、机制、适用场景和产品选型影响。"
            ),
            "interview": (
                "给出面试回答方法：先提供简短回答框架，再给一段精炼示范。不要生成长篇完整教程。"
            ),
        }
        titles = {
            "simpler": "再简单一点",
            "why": "为什么？",
            "example": "另一个例子",
            "technical": "技术细节",
            "compare": f"与{compare_concept}对比",
            "interview": "面试怎么答",
        }
        instruction = instructions.get(mode)
        if not instruction:
            raise ValueError("不支持的展开方式。")
        if mode == "technical" and point.extended_explanation:
            return {
                "title": "更多技术细节与原文信息",
                "content": point.extended_explanation,
            }
        fallback_content = {
            "simpler": point.core_explanation or point.level_1,
            "why": f"原因1：{point.core_explanation or point.description}\n→ 导致对输入产生相应变化\n→ 最终影响模型或产品结果。",
            "example": point.teaching_example,
            "technical": point.description,
            "compare": f"请从定义、机制、适用场景和产品影响比较{point.name}与{compare_concept}。",
            "interview": f"定义 → 原因 → 例子 → AI PM意义。\n{point.core_explanation or point.level_1}",
        }[mode]
        result = await llm_service.complete_structured(
            TutorExpansionOutput,
            tutor_system(
                f"这是用户主动请求的按需展开。{instruction}输出控制在150至500中文字，"
                "只回答本次请求，不重复默认三模块。"
            ),
            f"{self._point_context(point)}\n已展示过的展开："
            f"{json.dumps(previous_content[-3:], ensure_ascii=False)}",
            fallback=lambda: TutorExpansionOutput(
                title=titles[mode], content=fallback_content
            ),
            max_tokens=700,
        )
        return result.model_dump()

    async def start_lesson_session(self, db: Session, lesson_id: int) -> dict:
        repository = Repository(db)
        lesson = repository.get_lesson(lesson_id)
        if not lesson:
            raise LookupError("课程页面不存在，请先采集课程。")

        result = await llm_service.complete_json(
            tutor_system(
                "使用主动回忆法和费曼学习法，完全依据课程正文建立学习材料，"
                "不得补充正文中没有的事实。"
            ),
            "请返回以下 JSON："
            '{"summary":"分层次的核心内容总结",'
            '"key_points":["3至7个可检验的关键知识点"],'
            '"first_question":"一道要求学习者用自己的话解释核心概念的问题"}'
            f"\n\n页面标题：{lesson.title}\n课程正文：\n{lesson.content[:60000]}",
        )
        summary = str(result.get("summary", "")).strip()
        key_points = [
            str(item).strip() for item in result.get("key_points", []) if str(item).strip()
        ]
        first_question = str(result.get("first_question", "")).strip()
        if not summary or not key_points or not first_question:
            raise RuntimeError("模型生成的学习材料不完整，请重试。")
        record = repository.create_lesson_study_session(
            lesson.id, summary, key_points[:7], first_question
        )
        return {
            "session_id": record.id,
            "lesson_title": lesson.title,
            "summary": summary,
            "key_points": key_points[:7],
            "question": first_question,
        }

    async def answer_lesson_question(self, db: Session, session_id: int, answer: str) -> dict:
        repository = Repository(db)
        record = repository.get_lesson_study_session(session_id)
        if not record:
            raise LookupError("学习会话不存在。")
        if record.completed:
            raise ValueError("本轮学习已经完成，请重新开始一轮学习。")
        lesson = repository.get_lesson(record.lesson_id)
        if not lesson:
            raise LookupError("关联的课程页面不存在。")

        history = json.loads(record.history_json)
        current_question = history[-1]["question"]
        key_points = json.loads(record.key_points_json)
        evaluation = await llm_service.complete_json(
            tutor_system(
                "依据课程正文严格但友善地评价回答。不要因为措辞不同而扣分，重点判断理解、"
                "完整性和实际应用。下一题必须优先覆盖本次遗漏或尚未考察的知识点，不能直接泄露答案。"
            ),
            "返回以下 JSON："
            '{"score":0到100的整数,"feedback":"具体点评和改进提示",'
            '"strengths":["回答中的亮点"],"gaps":["遗漏或误解"],'
            '"reference_answer":"完全依据课程正文给出的简洁示范答案，直接回答当前问题",'
            '"next_question":"针对薄弱点的下一道问题"}'
            f"\n\n关键知识点：{json.dumps(key_points, ensure_ascii=False)}"
            f"\n当前问题：{current_question}\n学习者回答：{answer}"
            f"\n课程正文：\n{lesson.content[:60000]}"
            f"\n历史记录：{json.dumps(history[-6:], ensure_ascii=False)}",
        )
        try:
            score = max(0, min(100, int(evaluation.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        feedback = str(evaluation.get("feedback", "")).strip() or "请结合课程内容补充回答。"
        strengths = [str(item) for item in evaluation.get("strengths", [])][:5]
        gaps = [str(item) for item in evaluation.get("gaps", [])][:5]
        reference_answer = str(evaluation.get("reference_answer", "")).strip()
        if not reference_answer:
            reference_answer = "本题暂无参考答案，请结合反馈和本页关键知识点重新组织回答。"
        next_question = str(evaluation.get("next_question", "")).strip()

        previous_scores = [item["score"] for item in history if item.get("role") == "learner"]
        scores = [*previous_scores, score]
        mastery_score = round(sum(scores) / len(scores))
        answered_count = record.answered_count + 1
        completed = score >= 60 or answered_count >= self.max_rounds
        if not completed and not next_question:
            next_question = "请用一个具体的产品案例说明你对本页核心内容的理解。"

        history.append(
            {
                "role": "learner",
                "answer": answer,
                "score": score,
                "feedback": feedback,
                "strengths": strengths,
                "gaps": gaps,
                "reference_answer": reference_answer,
            }
        )
        if not completed:
            history.append({"role": "coach", "question": next_question})
        repository.update_lesson_study_session(record, history, mastery_score, completed)
        return {
            "score": score,
            "mastery_score": mastery_score,
            "feedback": feedback,
            "strengths": strengths,
            "gaps": gaps,
            "reference_answer": reference_answer,
            "next_question": None if completed else next_question,
            "answered_count": answered_count,
            "completed": completed,
        }


study_service = StudyService()
