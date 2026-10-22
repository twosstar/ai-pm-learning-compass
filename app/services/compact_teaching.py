"""Explicitly authored teaching notes; no model calls or automatic prose truncation.

Original explanations/examples/provenance remain authoritative. The per-point notes
reorganize that material for job seekers; they are not excerpts or new source reviews.
"""
import json
from pathlib import Path

TEACHING_DIR = Path(__file__).parents[1] / 'data' / 'teaching'
TEACHING_VERSION = 'compact-all60-v1'
NOTE_FIELDS = {'meaning', 'action', 'boundary', 'flow', 'branch', 'mistake'}


def apply_compact_teaching(payload: dict, excluded_lesson: int = 102) -> None:
    notes = {}
    for path in sorted(TEACHING_DIR.glob('M*.json')):
        module_notes = json.loads(path.read_text(encoding='utf-8'))
        for key, note in module_notes.items():
            point_id = int(key)
            if point_id in notes:
                raise ValueError(f'duplicate teaching note: {point_id}')
            if set(note) != NOTE_FIELDS or not all(isinstance(value, str) and value.strip() for value in note.values()):
                raise ValueError(f'incomplete teaching note: {point_id}')
            notes[point_id] = note
    expected = {point['id'] for lesson in payload['lessons'] if lesson['id'] != excluded_lesson
                for point in lesson['knowledge_points']}
    if set(notes) != expected:
        raise ValueError(f'teaching ID coverage mismatch: missing={sorted(expected - notes.keys())}; extra={sorted(notes.keys() - expected)}')
    for lesson in payload['lessons']:
        if lesson['id'] == excluded_lesson:
            continue
        for point in lesson['knowledge_points']:
            note = notes[point['id']]
            steps = note['flow'].split('|')
            if len(steps) != 5 or any(not step.strip() for step in steps):
                raise ValueError(f'invalid teaching flow: {point["id"]}')
            point['quick_study'] = {
                'essentials': [f'是什么：{note["meaning"]}', f'怎么用：{note["action"]}', f'边界：{note["boundary"]}'],
                'flow_title': f'{point["name"]}：判断与应用路径',
                'flow': [{'label': label, 'owner': f'第 {index} 步'} for index, label in enumerate(steps, 1)],
                'branches': [note['branch']],
                'example': point['teaching_example'],
                'interview': f'面试要会：{point["ai_pm_relevance"]}',
            }
            point['teaching_sections'] = [
                {'title': '原理与为什么', 'paragraphs': [point['core_explanation'], point['why_explanation']]},
                {'title': '原创业务案例', 'paragraphs': [point['teaching_example']]},
                {'title': '应用边界与常见误区', 'paragraphs': [note['boundary'], note['mistake']]},
                {'title': '工作中怎么用', 'paragraphs': [note['action']],
                 'steps': steps, 'basis': 'original-teaching-organization'},
                {'title': '面试需要掌握的深度', 'paragraphs': [point['ai_pm_relevance'],
                    '围绕本知识点说明原理、使用场景、选择依据与失败处理；基础面试不要求数学推导、算法证明或底层代码。']},
            ]
        lesson['teaching_version'] = TEACHING_VERSION
    payload['version'] = TEACHING_VERSION
