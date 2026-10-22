"""Original, lesson-aligned employment cases; no private question banks."""
import json
from functools import lru_cache
from pathlib import Path
from app.schemas.learning import GeneratedQuestion, QuestionFingerprint
from app.services.public_curriculum import teaching_pilot

PUBLIC_ROLES = {'general_ai_pm': '通用 AI 产品经理', 'ai_education_pm': 'AI+教育产品经理'}


@lru_cache(maxsize=1)
def feedback_guides() -> dict:
    return json.loads((Path(__file__).parents[1] / 'data/lesson102_feedback.json').read_text(encoding='utf-8'))


def reference_guide(point, attempt) -> dict | None:
    if getattr(point, 'lesson_id', None) != 102 or not (getattr(point, 'source_url', '') or '').startswith('public://'):
        return None
    try:
        scenario = json.loads(attempt.question_fingerprint_json or '{}').get('scenario', '')
    except (TypeError, ValueError):
        return None
    key = scenario.removeprefix('employment_')
    # Match the exact authored case, not just the lesson or the last displayed question.
    guide = feedback_guides().get(key)
    role = getattr(attempt, 'target_role', '')
    if not guide or not key.startswith(f'{point.id}_{role}_'):
        return None
    variant = key.rsplit('_', 1)[-1]
    case = teaching_pilot()['practice_cases'][str(point.id)][role]
    return guide if case.get(variant) == attempt.question else None


def employment_question(point, role: str, difficulty: int, stage: str) -> GeneratedQuestion | None:
    if point.lesson_id != 102 or not (getattr(point, 'source_url', '') or '').startswith('public://'):
        return None
    case = teaching_pilot()['practice_cases'].get(str(point.id))
    if not case:
        return None
    variant = 'retest' if stage in {'targeted', 'retest'} else 'probe' if stage == 'probe' else 'initial'
    scenario_role = role if role in PUBLIC_ROLES else 'general_ai_pm'
    rubric = {
        (1003, 'initial'): [
            '围绕减少材料整理或有效辅导说明首版范围，而不是一味扩大自动化',
            '把模型理解生成与规则、权限、记录或实际执行分开',
            '给出确认、信息不足和工具失败时的可恢复路径',
        ],
        (1003, 'probe'): [
            '先澄清具体任务或核查失败证据，不把表达变化等同于路径变化',
            '说明固定流程为何可能足够，以及改用 Agent 所需的新证据',
            '保留受控权限与必要确认，而不是给所有工具自由访问',
        ],
        (1003, 'retest'): [
            '超时不代表未执行，先查询或核对业务状态',
            '由执行层防止重复提交或写入，不让模型盲目无限重试',
            '给用户明确的处理中或待确认状态，不假报成功',
        ],
        (1004, 'initial'): [
            '区分资料过期或不匹配、检索错误和生成误读，不直接归因于模型大小',
            '核对引用是否适用并支持结论，用验证结果决定先改哪一步',
            '说明资料不足时的澄清或人工路径，不强行给确定答案',
        ],
        (1004, 'probe'): [
            '先确认适用对象或问题范围，不能因搜到资料就强行回答',
            '明确证据能支持的结论与不能覆盖的部分',
            '设计澄清或人工协助路径，给出对应的验证办法',
        ],
        (1004, 'retest'): [
            '在资料访问或检索阶段限制权限范围，不把保密只交给提示词',
            '不把输出提示词或脱敏当成资料访问控制的替代品',
            '无可用证据时说明限制、澄清或转人工，而不是自由编造',
        ],
    }[(point.id, variant)]
    return GeneratedQuestion(
        question_type='场景Case题', difficulty=difficulty,
        question=case[scenario_role][variant], target_role=role,
        interview_depth='P1', interview_value=point.interview_value,
        interview_category='产品设计 / Case',
        assessment_focus=[point.name, '岗位情境判断', '方案取舍', '失败处理'],
        why_interviewer_asks=case['why'], must_have_points=rubric,
        bonus_points=case['bonus_points'],
        unnecessary_detail='不要求画图、代码或算法推导；可用文字描述流程。未给出的业务数据无需编造，合理且说明依据的替代方案同样可接受。',
        question_fingerprint=QuestionFingerprint(
            knowledge_point=point.name, question_type='场景Case题',
            tested_skill='product_decision_with_constraints',
            scenario=f'employment_{point.id}_{scenario_role}_{variant}',
            reasoning_target=f'{variant}_scope_evidence_risk_tradeoff',
            expected_answer_dimensions=['目标', '判断依据', '取舍', '失败出口'],
        ),
    )
