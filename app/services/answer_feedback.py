"""Small, non-scoring helpers for clearer post-answer learning feedback."""

import re

FRAMEWORK_VERSION = 2


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        output = []
        for item in value:
            if isinstance(item, str) and item.strip():
                output.append(item.strip())
            elif isinstance(item, dict):
                output.extend(_strings(list(item.values())))
        return output
    if isinstance(value, dict):
        return _strings(list(value.values()))
    return []


def _cjk_bigrams(value: str) -> set[str]:
    groups = re.findall(r"[\u3400-\u9fff]{2,}", value)
    return {group[index : index + 2] for group in groups for index in range(len(group) - 1)}


def _candidate_is_grounded(candidate: list[str], evidence: str) -> bool:
    evidence_bigrams = _cjk_bigrams(evidence)
    for step in candidate:
        step_bigrams = _cjk_bigrams(step)
        overlap = step_bigrams & evidence_bigrams
        if not overlap or len(overlap) / max(1, len(step_bigrams)) < 0.16:
            return False
    return True


def _source_anchors(rubric: dict, expert_answer: str) -> list[str]:
    anchors = []
    for key in ("must_have_points", "assessment_focus", "bonus_points"):
        anchors.extend(_strings(rubric.get(key)))
    if len(anchors) < 4:
        anchors.extend(
            part.strip()
            for part in re.split(r"(?<=[。！？；，,])", expert_answer or "")
            if len(part.strip()) >= 5
        )
    unique = []
    seen = set()
    for anchor in anchors:
        normalized = re.sub(r"\W", "", anchor).casefold()
        if normalized and normalized not in seen:
            unique.append(anchor)
            seen.add(normalized)
    return unique


def _reextract_framework(rubric: dict, expert_answer: str) -> list[str]:
    anchors = _source_anchors(rubric, expert_answer)
    if len(anchors) < 4:
        return []
    transitions = (
        "先明确「{anchor}」在本题中的作用。",
        "再解释「{anchor}」如何影响关键判断。",
        "接着说明「{anchor}」对应的方案选择。",
        "然后用「{anchor}」验证实际效果。",
        "再结合「{anchor}」明确产品行动。",
        "最后依据「{anchor}」说明适用边界。",
    )
    for count in range(min(6, len(anchors)), 3, -1):
        framework = []
        for index, anchor in enumerate(anchors[:count]):
            anchor = anchor.strip(" ：:；。！？\"“”「」")
            if len(anchor) > 16:
                anchor = anchor[:15].rstrip("，、；：") + "…"
            framework.append(transitions[index].format(anchor=anchor))
        length = sum(map(len, framework))
        if 80 <= length <= 150:
            return framework
    return []


def generate_answer_framework(
    question: str,
    rubric,
    user_answer: str,
    expert_answer: str,
    candidate_framework=None,
) -> tuple[list[str], str]:
    """Validate framework from the existing scoring call, then re-extract locally if needed.

    No model request is made here. Every substantive step is checked against the question,
    rubric, or verified expert answer so the framework cannot add scoring requirements.
    """
    rubric_data = rubric if isinstance(rubric, dict) else {"must_have_points": _strings(rubric)}
    evidence = " ".join([question or "", user_answer or "", expert_answer or "", *_strings(rubric_data)])
    candidate = [item.strip() for item in _strings(candidate_framework) if item.strip()]
    total_length = sum(len(item) for item in candidate)
    generic_steps = {"业务目标", "关键分析", "产品判断", "结果复盘"}
    if (
        4 <= len(candidate) <= 6
        and 80 <= total_length <= 150
        and not all(item.strip(" ：:。；") in generic_steps for item in candidate)
        and _candidate_is_grounded(candidate, evidence)
    ):
        return candidate, "READY"

    extracted = _reextract_framework(rubric_data, expert_answer)
    extracted_length = sum(len(item) for item in extracted)
    if 4 <= len(extracted) <= 6 and 80 <= extracted_length <= 150:
        return extracted, "READY"
    return [], "FRAMEWORK_GENERATION_FAILED"


def prioritized_key_gaps(raw_gaps, missing_points, must_have_points) -> list[dict[str, str]]:
    """Keep at most three high-impact gaps and add grounded coaching if needed."""
    required = _strings(must_have_points)
    gaps = []
    seen = set()
    for item in raw_gaps or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        point = str(item.get("point", "")).strip()
        if not point or point in seen:
            continue
        gaps.append(
            {
                "point": point,
                "why_it_matters": str(item.get("why_it_matters", "")).strip(),
                "direction": str(item.get("direction", "")).strip(),
            }
        )
        seen.add(point)
        if len(gaps) == 3:
            break
    for point in _strings(missing_points):
        if len(gaps) == 3:
            break
        if point in seen:
            continue
        is_required = any(point in requirement or requirement in point for requirement in required)
        gaps.append(
            {
                "point": point,
                "why_it_matters": (
                    "这是本题明确的必答点；缺少它会削弱核心结论的完整性。"
                    if is_required
                    else "这个缺口会让关键判断缺少依据，难以证明方案适用于题目场景。"
                ),
                "direction": f"尝试用自己的话补充「{point}」与本题结论之间的联系。",
            }
        )
        seen.add(point)
    return gaps
