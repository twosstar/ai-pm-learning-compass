"""Optional browser acceptance check: temporary records, synthetic key, no provider network."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
storage = Path(tempfile.mkdtemp(prefix='copilot-browser-model-'))
os.environ.update(DATABASE_URL='sqlite:///' + (storage / 'app.db').as_posix(),
                  STORAGE_DIR=str(storage), CHROMA_PATH=str(storage / 'chroma'), LLM_API_KEY='')

import httpx
import uvicorn
from openai import AsyncOpenAI
from playwright.sync_api import sync_playwright
from app.main import app
from app.services.llm import LLMService
from app.api.routes import public_model_settings
from app.services import study
from app.schemas.learning import AnswerEvaluationOutput

calls = []
def provider(request):
    calls.append(request)
    output = AnswerEvaluationOutput(
        concept_accuracy=18, technical_understanding=18, product_thinking=18,
        application_scenario=18, communication_structure=18,
        correct_points=['分工清楚'], missing_points=[], improved_answer='模型预填，程序校验，员工确认，超时查状态。',
        expert_answer='提交层保证幂等。', next_action='advance', answer_level='优秀', score_explanation='模拟接口验收。',
    )
    return httpx.Response(200, json={'id': 'mock', 'object': 'chat.completion', 'created': 1,
        'model': 'mock-model', 'choices': [{'index': 0, 'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': output.model_dump_json()}}]})

LLMService._make_client = staticmethod(lambda key, base: AsyncOpenAI(
    api_key=key, base_url=base, max_retries=0,
    http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider))))
service = LLMService()
public_model_settings.llm_service = study.llm_service = service
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
for _ in range(200):
    if server.started:
        break
    time.sleep(.05)
assert server.started
canary = 'synthetic-browser-credential-not-real'
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{port}/')
        page.locator('#model-config-status').filter(has_text='未配置').wait_for()
        page.locator('#lesson-search').fill('工作流、模型与知识检索的组合')
        page.get_by_role('button', name='查看本节：工作流、模型与知识检索的组合', exact=True).click()
        page.locator('#start-practice').click()
        page.locator('#answer').fill('先做票据识别和预填，程序查重校验，员工确认后提交。超时查状态并防重。')
        page.locator('#draft-save-status').filter(has_text='已保存到本机').wait_for()
        page.locator('#answer').evaluate('(el) => el.blur()')
        page.locator('#session').screenshot(path=str(ROOT / 'docs' / 'images' / 'practice-question.png'))
        page.locator('#submit-answer').click()
        page.locator('#feedback').filter(has_text='尚未完成评价 · 不计分').wait_for()
        page.locator('#open-model-settings').click()
        page.locator('#model-base-url').fill('https://model.example/v1')
        page.locator('#model-name').fill('mock-model')
        page.locator('#model-api-key').fill(canary)
        page.locator('#model-consent').check()
        page.locator('#save-model-settings').click()
        page.locator('#model-settings-message').filter(has_text='已保存到本次运行内存').wait_for()
        assert len(calls) == 0
        assert page.locator('#model-api-key').input_value() == ''
        assert canary not in page.evaluate('JSON.stringify([localStorage, sessionStorage])')
        assert canary not in page.request.get(f'http://127.0.0.1:{port}/api/model-settings').text()
        page.locator('#close-model-settings').click()
        page.locator('#submit-answer').click()
        page.locator('#feedback').filter(has_text='90 分').wait_for()
        assert calls and service.public_status()['verified']
        page.locator('#session').screenshot(path=str(ROOT / 'docs' / 'images' / 'score-feedback.png'))
        page.locator('#open-model-settings').click()
        assert page.locator('#model-api-key').input_value() == ''
        page.set_viewport_size({'width': 375, 'height': 812})
        box = page.locator('#model-settings-dialog').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 375
        assert page.locator('#model-settings-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(storage / 'model-settings-mobile.png'))
        page.locator('#clear-model-settings').click()
        page.locator('#model-settings-message').filter(has_text='当前运行配置已清除').wait_for()
        assert not service._configured
        page.locator('#model-api-key').fill(canary)
        page.keyboard.press('Escape')
        assert page.locator('#model-api-key').input_value() == ''
        assert not errors, errors
        browser.close()
    print(json.dumps({'result': 'passed', 'checks': ['offline-save', 'memory-config', 'retry-model-score-90', 'no-browser-secret-storage', 'clear', 'mobile-fit', 'escape-clears-password'], 'evidence': str(storage)}, ensure_ascii=False))
finally:
    server.should_exit = True
    thread.join(timeout=10)
