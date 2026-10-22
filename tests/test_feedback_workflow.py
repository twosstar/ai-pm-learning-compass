import json
from types import SimpleNamespace

from app.services.public_curriculum import lesson_definition
from app.services.public_practice import employment_question, reference_guide


def test_reference_answer_matches_exact_role_question_and_stage():
    for point_id in (1003, 1004):
        point = SimpleNamespace(id=point_id, lesson_id=102, source_url='public://ai-pm-foundations/102', name='fixture', interview_value=4)
        for role in ('general_ai_pm', 'ai_education_pm'):
            for stage in ('initial', 'probe', 'retest'):
                question = employment_question(point, role, 1, stage)
                attempt = SimpleNamespace(question=question.question, target_role=role, question_fingerprint_json=question.question_fingerprint.model_dump_json())
                guide = reference_guide(point, attempt)
                assert guide and len(guide['answer']) <= 300
                assert len(guide['framework']) == 4
                attempt.question = 'unrelated question'
                assert reference_guide(point, attempt) is None


def test_quick_teaching_is_short_and_preserves_deeper_material():
    for point in lesson_definition(102)['knowledge_points']:
        quick = point['quick_study']
        assert len(quick['essentials']) == 3
        assert len(quick['flow']) == 5
        assert quick['branches']
        assert len(''.join(quick['essentials']) + quick['example'] + quick['interview']) < 350
        assert len(point['teaching_sections']) == 7


def test_unavailable_evaluator_does_not_assign_53_or_mutate_progress_and_can_retry(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import SessionLocal
    from app.db.models import AnswerEvaluation, KnowledgePoint, LearningSession, MasteryScore, QuestionAttempt, Weakness, ReviewHistory
    from app.db.repository import Repository
    from app.services import study
    from app.schemas.learning import AnswerEvaluationOutput

    class Offline:
        _configured = False
        async def complete_structured(self, schema, system, user, fallback, **kwargs):
            return fallback()

    monkeypatch.setattr(study, 'llm_service', Offline())
    with TestClient(app) as client:
        start = client.post('/api/study/start', json={'lesson_id': 102}).json()
        with SessionLocal() as db:
            point = db.get(KnowledgePoint, 1003)
            question = employment_question(point, 'general_ai_pm', 2, 'retest')
            attempt = Repository(db).create_question_attempt(start['session_id'], 1003, question, 'targeted')
            session = db.get(LearningSession, start['session_id'])
            session.current_knowledge_point_id = 1003
            db.commit()
            attempt_id = attempt.id
            score_before = [(row.knowledge_point_id, row.mastery_score, row.interview_readiness) for row in db.query(MasteryScore).order_by(MasteryScore.id)]
            counts_before = [db.query(model).count() for model in (AnswerEvaluation, Weakness, ReviewHistory)]
        answer = '两周上线，我优先做票据结构化提取、独立的规则校验层和人机确认卡点。强财务规则、最终提交、发票验真不能交给模型。提交时带上幂等单号，如果超时，前端禁止用户重复提交，后台异步轮询查询订单状态，区分提交成功、失败还是丢单，再同步状态给员工。'
        body = {'session_id': start['session_id'], 'question_attempt_id': attempt_id, 'answer': answer}
        response = client.post('/api/study/answer', json=body)
        assert response.status_code == 200, response.text
        feedback = response.json()
        assert feedback['total_score'] is None
        assert feedback['dimensions'] is None
        assert feedback['pass_status'] == 'UNASSESSED'
        assert feedback['evaluation_source'] == 'offline'
        assert '尚未配置评分模型' in feedback['score_explanation']
        assert feedback['next_action'] == 'retry_evaluation'
        assert feedback['next_question'] is None
        assert feedback['correct_points'] == feedback['missing_points'] == []
        assert feedback['evaluated_question'] == question.question
        assert '超时只能说明' in feedback['expert_answer']
        assert '两周上线' not in feedback['expert_answer']
        assert '可以把 AI 功能看成' not in feedback['expert_answer']
        with SessionLocal() as db:
            assert db.get(QuestionAttempt, attempt_id).user_answer == answer
            assert [db.query(model).count() for model in (AnswerEvaluation, Weakness, ReviewHistory)] == counts_before
            assert [(row.knowledge_point_id, row.mastery_score, row.interview_readiness) for row in db.query(MasteryScore).order_by(MasteryScore.id)] == score_before

        class Scored(Offline):
            async def complete_structured(self, schema, system, user, fallback, **kwargs):
                if schema is AnswerEvaluationOutput:
                    return AnswerEvaluationOutput(
                        concept_accuracy=18, technical_understanding=18, product_thinking=18,
                        application_scenario=18, communication_structure=18,
                        correct_points=['明确保留规则与确认', '说明幂等和超时查状态'],
                        missing_points=[], improved_answer='我不会盲目重试，先查询提交状态，由执行层保证幂等，并向用户展示明确结果。',
                        expert_answer='先查状态，再决定是否重试，执行层防重，界面反馈真实状态。',
                        next_action='advance', answer_level='优秀', score_explanation='测试评价：已覆盖本题核心判断。',
                    )
                return fallback()

        monkeypatch.setattr(study, 'llm_service', Scored())
        retry = client.post('/api/study/answer', json=body)
        assert retry.status_code == 200, retry.text
        assert retry.json()['total_score'] == 90
        assert retry.json()['evaluation_source'] == 'model'
        assert retry.json()['missing_points'] == []
        with SessionLocal() as db:
            assert db.query(AnswerEvaluation).filter_by(question_attempt_id=attempt_id).count() == 1
        assert client.post('/api/study/answer', json=body).status_code == 409
