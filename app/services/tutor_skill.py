from functools import lru_cache
from pathlib import Path

SKILL_PATH = Path(__file__).parents[1] / "prompts" / "AI_PM_TUTOR_SKILL.md"
FALLBACK_SKILL = (
    "你是一名负责培养AI产品经理的AI产品负责人。技术教学必须关联产品价值、真实业务、"
    "技术机制与面试表达，不能只解释概念。"
)


@lru_cache(maxsize=1)
def load_tutor_skill() -> str:
    try:
        content = SKILL_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_SKILL
    return content or FALLBACK_SKILL


def tutor_system(task_instruction: str) -> str:
    return f"{load_tutor_skill()}\n\n## 当前任务\n{task_instruction}"
