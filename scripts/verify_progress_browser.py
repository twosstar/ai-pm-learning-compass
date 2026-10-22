"""Local acceptance and publishable screenshots; temporary demo data, no API key."""
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
storage = Path(tempfile.mkdtemp(prefix='copilot-progress-'))
os.environ.update(DATABASE_URL='sqlite:///' + (storage / 'app.db').as_posix(),
                  STORAGE_DIR=str(storage), CHROMA_PATH=str(storage / 'chroma'), LLM_API_KEY='')

import uvicorn
from playwright.sync_api import sync_playwright
from app.main import app

screens = ROOT / 'docs' / 'images'
screens.mkdir(parents=True, exist_ok=True)
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
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page = context.new_page()
        errors, starts = [], []
        def watch(tab):
            tab.on('pageerror', lambda error: errors.append(str(error)))
            tab.on('request', lambda request: starts.append(request.url) if request.method == 'POST' and request.url.endswith('/study/start') else None)
        watch(page)
        base = f'http://127.0.0.1:{port}'
        page.goto(base)
        page.locator('#progress-summary').filter(has_text='已完成').wait_for()
        assert page.locator('#resume-learning').is_enabled()
        assert page.locator('#resume-learning').inner_text() == '开始第一节'
        assert page.locator('.module-shortcut').count() == 10
        page.locator('#resume-learning').click()
        page.locator('#lesson-title').filter(has_text='从用户问题到 AI 产品机会').wait_for()
        assert not starts, 'Opening the first reader must not create a question or call a model'
        page.locator('#back-catalog').click()
        page.locator('.module-shortcut').last.click()
        assert page.locator('.course-module').last.evaluate('(el) => el.open')
        page.locator('#lesson-search').fill('监督微调与 LoRA')
        page.get_by_role('button', name='查看本节：监督微调与 LoRA', exact=True).click()
        page.locator('#knowledge-point-411282 .read-marker').click()
        page.locator('#knowledge-point-411282 .read-marker').filter(has_text='已读').wait_for()
        page.locator('#knowledge-point-411282').evaluate('(el) => window.scrollTo(0, scrollY + el.getBoundingClientRect().top + 80)')
        page.wait_for_timeout(1000)
        assert page.request.get(base + '/api/progress/lessons/128/resume').json()['point_id'] == 411282
        page.reload()
        page.locator('#resume-title').filter(has_text='监督微调').wait_for()
        page.locator('#resume-learning').click()
        page.locator('#lesson-title').filter(has_text='监督微调与 LoRA').wait_for()
        assert abs(page.locator('#knowledge-point-411282').bounding_box()['y']) < 160
        assert page.locator('#knowledge-point-411282 .read-marker').get_attribute('aria-pressed') == 'true'
        page.locator('#start-practice').click()
        page.locator('#answer').fill('演示草稿：先审核样本口径，模型适配稳定输出格式；最新政策仍需用现行资料核查。')
        page.locator('#draft-save-status').filter(has_text='已保存到本机').wait_for()
        attempt = page.request.get(base + '/api/progress/lessons/128/resume').json()['practice']['question_attempt_id']
        context.close()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page = context.new_page()
        watch(page)
        page.goto(base)
        page.locator('#resume-title').filter(has_text='监督微调').wait_for()
        page.screenshot(path=str(screens / 'learning-dashboard.png'))
        page.locator('#resume-learning').click()
        page.locator('#answer').filter(visible=True).wait_for()
        assert '演示草稿' in page.locator('#answer').input_value()
        assert page.request.get(base + '/api/progress/lessons/128/resume').json()['practice']['question_attempt_id'] == attempt
        assert len(starts) == 1
        page.locator('#submit-answer').click()
        page.locator('#feedback').filter(has_text='尚未完成评价 · 不计分').wait_for()
        page.screenshot(path=str(screens / 'practice-offline.png'))
        page.reload()
        page.locator('#resume-title').filter(has_text='监督微调').wait_for()
        page.locator('#resume-learning').click()
        page.locator('#answer').filter(visible=True).wait_for()
        assert '演示草稿' in page.locator('#answer').input_value()
        assert page.locator('#submit-answer').is_enabled()
        assert len(starts) == 1
        page.locator('#review-knowledge').click()
        page.locator('#back-catalog').click()
        page.locator('#progress-summary').filter(has_text='已读 1').wait_for()
        page.locator('#lesson-search').fill('工作流、模型与知识检索的组合')
        page.get_by_role('button', name='查看本节：工作流、模型与知识检索的组合', exact=True).click()
        page.locator('#knowledge-point-1003').scroll_into_view_if_needed()
        page.screenshot(path=str(screens / 'lesson-reader.png'))
        page.get_by_role('button', name='概念地图', exact=True).click()
        assert page.locator('#concepts h2').bounding_box()['y'] >= 0
        page.locator('#concept-search').fill('RAG')
        page.locator('.concept-card').first.wait_for()
        page.screenshot(path=str(screens / 'concept-map.png'))
        page.get_by_role('button', name='智能学习', exact=True).click()
        page.locator('#back-catalog').click()
        page.set_viewport_size({'width': 375, 'height': 812})
        page.evaluate('window.scrollTo(0, 0)')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(screens / 'mobile-dashboard.png'))
        for width in [320, 700, 768, 1024, 1440]:
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        page.locator('#open-model-settings').click()
        assert page.locator('#model-settings-dialog').is_visible()
        page.locator('#close-model-settings').click()
        assert not errors, errors
        context.close()
        browser.close()
    print(json.dumps({'result': 'passed', 'checks': ['reading-reload', 'explicit-read-not-mastery', 'new-browser-context-resume', 'exact-attempt-draft', 'pending-answer-retry', 'one-start-only', 'mobile-fit', 'demo-screenshots'], 'evidence': str(storage)}, ensure_ascii=False))
finally:
    server.should_exit = True
    thread.join(timeout=10)
