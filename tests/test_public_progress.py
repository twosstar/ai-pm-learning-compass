from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.db.models import MasteryScore, QuestionAttempt, AnswerEvaluation, LearningSession
from app.db.session import SessionLocal


@pytest.fixture
def client():
    with TestClient(app, base_url='http://127.0.0.1:8001', client=('127.0.0.1', 50123)) as value:
        yield value


def test_reading_bookmark_and_explicit_read_do_not_award_mastery(client):
    with SessionLocal() as db:
        before = [(row.id, row.mastery_score) for row in db.query(MasteryScore).order_by(MasteryScore.id)]
    response = client.post('/api/progress/checkpoint', json={'lesson_id': 128, 'point_id': 411282,
                          'position': .35, 'view': 'reading', 'read': True})
    assert response.status_code == 200, response.text
    progress = client.get('/api/progress').json()
    lesson = next(row for row in progress['lessons'] if row['lesson_id'] == 128)
    assert lesson['status'] == 'reading' and lesson['read_count'] == 1
    restored = client.get('/api/progress/lessons/128/resume').json()
    assert restored['view'] == 'reading' and restored['point_id'] == 411282
    assert restored['position'] == .35
    with SessionLocal() as db:
        assert [(row.id, row.mastery_score) for row in db.query(MasteryScore).order_by(MasteryScore.id)] == before


def test_draft_and_pending_answer_resume_exact_attempt_without_model_calls(client):
    start = client.post('/api/study/start', json={'lesson_id': 102, 'target_role': 'ai_education_pm'}).json()
    attempt_id = start['question_attempt_id']
    draft = {'session_id': start['session_id'], 'attempt_id': attempt_id, 'text': '未提交草稿：程序负责权限，模型负责辅助讲解。'}
    assert client.post('/api/progress/draft', json=draft).status_code == 200
    client.post('/api/progress/checkpoint', json={'lesson_id': 102, 'point_id': start['current_knowledge_point']['id'], 'view': 'practice'})
    with SessionLocal() as db:
        before = db.query(QuestionAttempt).count()
    for _ in range(2):
        restored = client.get('/api/progress/lessons/102/resume').json()['practice']
        assert restored['question_attempt_id'] == attempt_id
        assert restored['question']['target_role'] == 'ai_education_pm'
        assert restored['draft_answer'] == draft['text'] and not restored['evaluated']
    with SessionLocal() as db:
        assert db.query(QuestionAttempt).count() == before
    pending = client.post('/api/study/answer', json={'session_id': start['session_id'], 'question_attempt_id': attempt_id, 'answer': '已提交但模型不可用的回答'}).json()
    assert pending['total_score'] is None
    assert client.get('/api/progress/lessons/102/resume').json()['practice']['draft_answer'] == '已提交但模型不可用的回答'


def test_evaluated_answer_is_restored_not_regraded_and_can_continue(client):
    start = client.post('/api/study/start', json={'lesson_id': 101}).json()
    with SessionLocal() as db:
        attempt = db.get(QuestionAttempt, start['question_attempt_id'])
        attempt.user_answer = '历史已评分回答'
        db.add(AnswerEvaluation(question_attempt_id=attempt.id, total_score=90,
            concept_accuracy=18, technical_understanding=18, product_thinking=18,
            application_scenario=18, communication_structure=18, improved_answer='保存的优化答案', expert_answer='保存的参考'))
        db.get(LearningSession, start['session_id']).mode = 'advance'
        db.commit()
    restored = client.get('/api/progress/lessons/101/resume').json()['practice']
    assert restored['evaluated'] and restored['can_continue']
    assert restored['saved_feedback']['total_score'] == 90
    assert restored['draft_answer'] == '历史已评分回答'
    assert client.post('/api/progress/draft', json={'session_id': start['session_id'], 'attempt_id': start['question_attempt_id'], 'text': '覆盖历史'}).status_code == 409


def test_invalid_or_cross_lesson_progress_is_rejected(client):
    assert client.post('/api/progress/checkpoint', json={'lesson_id': 101, 'point_id': 411282}).status_code == 422
    assert client.post('/api/progress/checkpoint', json={'lesson_id': 101, 'point_id': 1001, 'position': 2}).status_code == 422
    assert client.get('/api/progress/lessons/99999/resume').status_code == 404
    assert client.post('/api/progress/checkpoint', json={'lesson_id': 101, 'point_id': 1001}, headers={'Origin': 'https://evil.example'}).status_code == 403


def test_legacy_practice_is_visible_without_reading_bookmark(client):
    from app.db.models import PublicReadingBookmark
    start = client.post('/api/study/start', json={'lesson_id': 160}).json()
    with SessionLocal() as db:
        bookmark = db.get(PublicReadingBookmark, 160)
        if bookmark:
            db.delete(bookmark)
        db.commit()
    record = next(row for row in client.get('/api/progress').json()['lessons'] if row['lesson_id'] == 160)
    assert record['status'] == 'practice' and record['read_count'] == 0
    resumed = client.get('/api/progress/lessons/160/resume').json()
    assert resumed['practice']['question_attempt_id'] == start['question_attempt_id']


def test_empty_draft_survives_restart_without_restoring_old_answer(client):
    start = client.post('/api/study/start', json={'lesson_id': 159}).json()
    with SessionLocal() as db:
        attempt = db.get(QuestionAttempt, start['question_attempt_id'])
        attempt.user_answer = '旧的待评分回答'
        from app.db.models import utcnow
        attempt.answered_at = utcnow()
        db.commit()
    assert client.post('/api/progress/draft', json={'session_id': start['session_id'], 'attempt_id': start['question_attempt_id'], 'text': ''}).status_code == 200
    with TestClient(app, base_url='http://127.0.0.1:8001', client=('127.0.0.1', 50124)) as restarted:
        assert restarted.get('/api/progress/lessons/159/resume').json()['practice']['draft_answer'] == ''
