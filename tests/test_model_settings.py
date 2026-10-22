import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.main import app
from app.services.llm import LLMService
from app.api.routes import public_model_settings as settings_route
from app.services import study
from app.schemas.learning import AnswerEvaluationOutput

CANARY = 'synthetic-test-credential-not-a-real-key'


@pytest.fixture
def local_model(monkeypatch):
    calls = []
    mode = {'auth_error': False}
    def respond(request):
        calls.append(request)
        if mode['auth_error']:
            return httpx.Response(401, json={'error': {'message': CANARY, 'type': 'authentication_error'}})
        output = AnswerEvaluationOutput(
            concept_accuracy=18, technical_understanding=18, product_thinking=18,
            application_scenario=18, communication_structure=18,
            correct_points=['分工清晰', '明确超时查状态与防重'], missing_points=[],
            improved_answer='先识别预填，程序校验，员工确认，超时查状态后受控重试。',
            expert_answer='规则和提交不由模型自行决定。', next_action='advance',
            answer_level='优秀', score_explanation='模拟评分验证，不代表真实供应商评价质量。',
        )
        return httpx.Response(200, json={
            'id': 'mock', 'object': 'chat.completion', 'created': 1, 'model': 'mock-model',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': output.model_dump_json()}}],
        })
    monkeypatch.setattr(LLMService, '_make_client', staticmethod(lambda key, base: AsyncOpenAI(
        api_key=key, base_url=base, max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )))
    service = LLMService()
    monkeypatch.setattr(settings_route, 'llm_service', service)
    monkeypatch.setattr(study, 'llm_service', service)
    with TestClient(app, base_url='http://127.0.0.1:8001', client=('127.0.0.1', 51234)) as client:
        yield client, service, calls, mode


def configuration(client, **overrides):
    token = client.get('/api/model-settings').json()['settings_token']
    payload = dict(base_url='https://model.example/v1', model='mock-model', api_key=CANARY, allow_provider_requests=True)
    payload.update(overrides)
    return client.put('/api/model-settings', json=payload, headers={'X-Local-Settings-Token': token, 'Origin': 'http://127.0.0.1:8001'})


def test_configuration_is_memory_only_and_save_does_not_call_provider(local_model):
    client, service, calls, _ = local_model
    response = configuration(client)
    assert response.status_code == 200, response.text
    assert response.json()['configured'] and not response.json()['verified']
    assert 'no-store' in response.headers['cache-control']
    assert CANARY not in response.text and 'api_key' not in response.text
    assert calls == []
    assert not LLMService()._configured
    cleared = client.delete('/api/model-settings', headers={'X-Local-Settings-Token': response.json()['settings_token']})
    assert cleared.status_code == 200 and not service._configured


@pytest.mark.parametrize('url', ['http://model.example/v1', 'https://localhost/v1', 'https://127.0.0.1/v1', 'https://10.0.0.1/v1', 'https://[::1]/v1', 'https://user:password@model.example/v1', 'https://model.example/v1?key=secret'])
def test_reject_unsafe_urls(local_model, url):
    client, service, calls, _ = local_model
    response = configuration(client, base_url=url)
    assert response.status_code == 400
    assert not service._configured and not calls
    assert CANARY not in response.text


def test_reject_cross_site_missing_token_and_redact_invalid_input(local_model):
    client, service, calls, _ = local_model
    assert client.put('/api/model-settings', json={}).status_code == 403
    token = client.get('/api/model-settings').json()['settings_token']
    assert client.get('/api/model-settings', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/model-settings', headers={'Host': 'evil.example'}).status_code == 403
    assert client.get('/api/model-settings', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    response = client.put('/api/model-settings', json={'api_key': {'bad': CANARY}}, headers={'X-Local-Settings-Token': token})
    assert response.status_code == 422 and CANARY not in response.text
    assert configuration(client, allow_provider_requests=False).status_code == 400
    assert not service._configured and not calls


def test_saved_answer_can_be_scored_after_runtime_configuration(local_model):
    client, service, calls, mode = local_model
    start = client.post('/api/study/start', json={'lesson_id': 102}).json()
    body = {'session_id': start['session_id'], 'question_attempt_id': start['question_attempt_id'],
            'answer': '先做票据识别和预填，程序查重校验，员工核对后提交。超时先查状态，再受控重试防重。'}
    pending = client.post('/api/study/answer', json=body)
    assert pending.status_code == 200, pending.text
    assert pending.json()['total_score'] is None
    assert configuration(client).status_code == 200
    assert calls == []
    scored = client.post('/api/study/answer', json=body)
    assert scored.status_code == 200, scored.text
    assert scored.json()['total_score'] == 90 and scored.json()['evaluation_source'] == 'model'
    assert client.get('/api/model-settings').json()['verified']
    assert len(calls) >= 1
    assert CANARY not in scored.text


@pytest.mark.asyncio
async def test_provider_error_body_never_becomes_feedback_or_logs(local_model, caplog):
    _, service, _, mode = local_model
    service.configure_runtime(CANARY, 'https://model.example/v1', 'mock-model')
    mode['auth_error'] = True
    fallback = lambda: AnswerEvaluationOutput(
        concept_accuracy=0, technical_understanding=0, product_thinking=0,
        application_scenario=0, communication_structure=0,
        correct_points=[], missing_points=[], improved_answer='', expert_answer='', next_action='remediate',
    )
    await service.complete_structured(AnswerEvaluationOutput, 'test', 'test', fallback)
    assert '认证失败' in service.public_status()['last_error']
    assert CANARY not in json.dumps(service.public_status()) + caplog.text
