from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import ClassVar


class TeachingContentPolicy:
    """Enforce a short, dense default layer while preserving detail for expansion."""

    FIELD_LIMITS: ClassVar[dict[str, int]] = {
        "core_explanation": 220,
        "why_explanation": 120,
        "teaching_example": 120,
        "ai_pm_relevance": 120,
    }
    TOTAL_LIMITS: ClassVar[dict[int, int]] = {1: 300, 2: 300, 3: 400, 4: 500, 5: 600}
    PROMOTIONAL_MARKERS = (
        "随着技术不断发展",
        "随着技术的快速演进",
        "应用场景持续扩展",
        "具有广阔前景",
        "广泛应用",
        "发展前景",
        "日益迫切",
    )
    DENSITY_MARKERS = (
        "负责",
        "通过",
        "基于",
        "导致",
        "因此",
        "如果",
        "例如",
        "用户",
        "指标",
        "准确",
        "成本",
        "时延",
        "风险",
        "决策",
        "约束",
        "检索",
        "生成",
        "输入",
        "输出",
        "模型",
        "产品",
        "数据",
    )
    LOW_DENSITY_PHRASES = (
        "它会改变信息的处理过程",
        "放进一个具体产品任务",
        "据此判断方案与业务目标是否匹配",
        "理解这个概念很重要",
        "这个技术应用广泛",
        "需要综合判断",
    )
    FIELD_KEYWORDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "core_explanation": ("是", "负责", "通过", "基于", "机制", "局限", "约束"),
        "why_explanation": ("因此", "否则", "要求", "风险", "影响", "不足", "无法", "需要"),
        "teaching_example": ("例如", "用户", "场景", "当", "在", "问", "系统"),
        "ai_pm_relevance": ("AI PM", "产品经理", "决定", "指标", "成本", "时延", "风险", "权衡"),
    }

    @staticmethod
    def length(text: str) -> int:
        return len(re.sub(r"\s+", "", text or ""))

    @classmethod
    def _units(cls, text: str) -> list[str]:
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return []
        parts = re.split(r"(?<=[。！？；.!?;])\s*", cleaned)
        units: list[str] = []
        for part in parts:
            if cls.length(part) <= 140:
                units.append(part.strip())
                continue
            units.extend(
                item.strip()
                for item in re.split(r"(?<=[，、：,:])\s*", part)
                if item.strip()
            )
        return units

    @classmethod
    def _strip_promotional(cls, units: list[str]) -> list[str]:
        return [
            unit
            for unit in units
            if not any(marker in unit for marker in cls.PROMOTIONAL_MARKERS)
        ]

    @staticmethod
    def similarity(left: str, right: str) -> float:
        left = re.sub(r"\W+", "", left or "").casefold()
        right = re.sub(r"\W+", "", right or "").casefold()
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    @classmethod
    def is_dense(cls, text: str) -> bool:
        value = " ".join((text or "").split())
        if cls.length(value) < 20:
            return False
        if any(phrase in value for phrase in cls.LOW_DENSITY_PHRASES):
            return False
        return any(marker.casefold() in value.casefold() for marker in cls.DENSITY_MARKERS)

    @classmethod
    def _shorten(
        cls,
        text: str,
        field: str,
        limit: int,
        avoid: tuple[str, ...] = (),
    ) -> str:
        units = cls._strip_promotional(cls._units(text))
        keywords = cls.FIELD_KEYWORDS[field]
        ranked = sorted(
            enumerate(units),
            key=lambda pair: (
                -sum(keyword.casefold() in pair[1].casefold() for keyword in keywords),
                pair[0],
            ),
        )
        chosen: list[tuple[int, str]] = []
        for index, unit in ranked:
            if any(cls.similarity(unit, prior) >= 0.68 for prior in avoid):
                continue
            if any(cls.similarity(unit, prior) >= 0.78 for _, prior in chosen):
                continue
            if cls.length("".join(value for _, value in chosen) + unit) > limit:
                continue
            chosen.append((index, unit))
            if field == "teaching_example" or len(chosen) >= (3 if field == "core_explanation" else 2):
                break
        if not chosen and units and not avoid:
            first = units[0]
            chosen = [(0, first[:limit])]
        result = "".join(value for _, value in sorted(chosen)).strip()
        return result[:limit].rstrip("，、：:；; ")

    @classmethod
    def default_total_limit(cls, importance: int) -> int:
        return cls.TOTAL_LIMITS.get(max(1, min(5, importance)), 400)

    @classmethod
    def total_length(cls, item) -> int:
        return sum(
            cls.length(getattr(item, field, "")) for field in cls.FIELD_LIMITS
        )

    @classmethod
    def redundancy_pairs(cls, item) -> list[tuple[str, str]]:
        fields = list(cls.FIELD_LIMITS)
        pairs = []
        for index, left in enumerate(fields):
            for right in fields[index + 1 :]:
                if cls.similarity(getattr(item, left, ""), getattr(item, right, "")) >= 0.62:
                    pairs.append((left, right))
        return pairs

    @classmethod
    def needs_refresh(cls, point, source_length: int) -> bool:
        values = [getattr(point, field, "") or "" for field in cls.FIELD_LIMITS]
        total = sum(cls.length(value) for value in values)
        importance = max(point.importance_for_ai_pm, point.importance_for_interview)
        if any(cls.length(value) > cls.FIELD_LIMITS[field] for field, value in zip(cls.FIELD_LIMITS, values)):
            return True
        if total > cls.default_total_limit(importance):
            return True
        if source_length >= 500 and total / source_length > 0.35:
            return True
        if any(not cls.is_dense(value) for value in values):
            return True
        return any(cls.similarity(values[i], values[j]) >= 0.62 for i in range(4) for j in range(i + 1, 4))

    @classmethod
    def enforce(cls, item, source_text: str = ""):
        original = {
            field: " ".join((getattr(item, field, "") or "").split())
            for field in cls.FIELD_LIMITS
        }
        if not getattr(item, "extended_explanation", ""):
            item.extended_explanation = "\n\n".join(
                f"{label}：{original[field]}"
                for field, label in (
                    ("core_explanation", "核心解释"),
                    ("why_explanation", "为什么"),
                    ("teaching_example", "教学例子"),
                    ("ai_pm_relevance", "AI PM关联"),
                )
                if original[field]
            )[:4000]
        importance = int(getattr(item, "interview_value", 3) or 3)
        total_budget = cls.default_total_limit(importance)
        source_length = cls.length(source_text)
        if source_length >= 500:
            total_budget = min(total_budget, max(200, int(source_length * 0.35)))
        budgets = {
            "core_explanation": min(220, round(total_budget * 0.37)),
            "why_explanation": min(120, round(total_budget * 0.20)),
            "teaching_example": min(120, round(total_budget * 0.22)),
            "ai_pm_relevance": min(120, round(total_budget * 0.21)),
        }
        core = cls._shorten(
            original["core_explanation"], "core_explanation", budgets["core_explanation"]
        )
        why = cls._shorten(
            original["why_explanation"], "why_explanation", budgets["why_explanation"], (core,)
        )
        example = cls._shorten(
            original["teaching_example"],
            "teaching_example",
            budgets["teaching_example"],
            (core, why),
        )
        relevance = cls._shorten(
            original["ai_pm_relevance"],
            "ai_pm_relevance",
            budgets["ai_pm_relevance"],
            (core, why, example),
        )
        fallbacks = {
            "core_explanation": cls._shorten(
                source_text, "core_explanation", budgets["core_explanation"]
            ),
            "why_explanation": cls._shorten(
                source_text, "why_explanation", budgets["why_explanation"], (core,)
            ),
            "teaching_example": cls._shorten(
                source_text, "teaching_example", budgets["teaching_example"], (core, why)
            ),
            "ai_pm_relevance": cls._shorten(
                source_text,
                "ai_pm_relevance",
                budgets["ai_pm_relevance"],
                (core, why, example),
            ),
        }
        values = {
            "core_explanation": core,
            "why_explanation": why,
            "teaching_example": example,
            "ai_pm_relevance": relevance,
        }
        for field, value in values.items():
            if not cls.is_dense(value) and cls.is_dense(fallbacks[field]):
                value = fallbacks[field]
            setattr(item, field, value)
        item.interview_requirements = list(item.interview_requirements[:4])
        item.unnecessary_detail = list(item.unnecessary_detail[:3])
        return item


teaching_content_policy = TeachingContentPolicy()
