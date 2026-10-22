from types import SimpleNamespace

from app.services.public_curriculum import lesson_definition, teaching_pilot
from app.services.public_practice import employment_question


def test_pilot_teaches_steps_boundaries_and_misconceptions():
    lesson = lesson_definition(102)
    assert [point['id'] for point in lesson['knowledge_points']] == [1003, 1004]
    assert len(lesson['objectives']) == 3
    for point in lesson['knowledge_points']:
        sections = point['teaching_sections']
        assert len(sections) == 7
        assert any('边界' in section['title'] for section in sections)
        assert any('误区' in section['title'] for section in sections)
        assert sum(len(section.get('steps', [])) for section in sections) >= 8
        assert sum(len(''.join(section.get('paragraphs', []) + section.get('steps', []))) for section in sections) > 700
        assert point['source_ids']


def test_pilot_has_distinct_role_and_retest_cases_with_explicit_rubrics():
    for point_id in (1003, 1004):
        point = SimpleNamespace(id=point_id, lesson_id=102, source_url='public://ai-pm-foundations/102', name='fixture', interview_value=4)
        texts = set()
        for role in ('general_ai_pm', 'ai_education_pm'):
            for stage in ('initial', 'probe', 'retest'):
                question = employment_question(point, role, 1, stage)
                assert question.target_role == role
                assert question.must_have_points and question.why_interviewer_asks
                assert '请围绕' not in question.question
                assert ('初中' in question.question or '学生' in question.question or '学习' in question.question) if role == 'ai_education_pm' else '学生' not in question.question
                texts.add(question.question)
        assert len(texts) == 6
    private_point = SimpleNamespace(id=1003, lesson_id=102, source_url='https://private.example')
    assert employment_question(private_point, 'general_ai_pm', 1, 'initial') is None


def test_education_goal_survives_retest_continue_and_next_lesson(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import study
    from tests.test_mastery_loop import FakeStructuredLLM
    from app.schemas.learning import GeneratedQuestion
    from app.db.session import SessionLocal
    from app.db.models import LearningSession, MasteryScore

    class OfflineLLM(FakeStructuredLLM):
        async def complete_structured(self, schema, system, user, fallback, retries=2, **kwargs):
            if schema is GeneratedQuestion:
                return fallback()
            return await super().complete_structured(schema, system, user, fallback, retries, **kwargs)

    monkeypatch.setattr(study, 'llm_service', OfflineLLM())
    with TestClient(app) as client:
        # Other integration tests may have visited the points. Reset only fixture scores.
        with SessionLocal() as db:
            db.query(MasteryScore).filter(MasteryScore.knowledge_point_id.in_([1003, 1004])).delete(synchronize_session=False)
            db.commit()
        assert client.post('/api/study/start', json={'lesson_id': 102, 'target_role': 'unknown'}).status_code == 422
        result = client.post('/api/study/start', json={'lesson_id': 102, 'target_role': 'ai_education_pm'}).json()
        first_text = result['question']['question']
        assert '学生' in first_text
        assert result['question']['target_role'] == 'ai_education_pm'
        session_id = result['session_id']
        answer = {'session_id': session_id, 'question_attempt_id': result['question_attempt_id'], 'answer': '模型处理理解与生成；系统核验权限与状态，学生确认后再写记录，失败时先查询状态。'}
        response = client.post('/api/study/answer', json=answer)
        assert response.status_code == 200, response.text
        feedback = response.json()
        assert feedback['next_question']['target_role'] == 'ai_education_pm'
        assert feedback['next_question']['question'] != first_text
        answer['question_attempt_id'] = feedback['next_attempt_id']
        assert client.post('/api/study/answer', json=answer).status_code == 200
        result = client.post('/api/study/continue', json={'session_id': session_id}).json()
        assert result['question']['target_role'] == 'ai_education_pm'
        answer['question_attempt_id'] = result['question_attempt_id']
        assert client.post('/api/study/answer', json=answer).status_code == 200
        result = client.post('/api/study/continue', json={'session_id': session_id}).json()
        assert result['lesson_id'] == 103
        assert result['question']['target_role'] == 'ai_education_pm'
        with SessionLocal() as db:
            assert db.get(LearningSession, result['session_id']).target_role == 'ai_education_pm'
        catalog = client.get('/api/catalog').json()['items'][0]['lessons'][1]
        assert len(catalog['knowledge_points'][0]['teaching_sections']) == 7
