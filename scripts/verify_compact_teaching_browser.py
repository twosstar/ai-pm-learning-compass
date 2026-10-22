"""Verify all lesson readers using temporary data and no configured model."""
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
storage = Path(tempfile.mkdtemp(prefix='copilot-compact60-'))
os.environ.update(DATABASE_URL='sqlite:///' + (storage / 'app.db').as_posix(),
                  STORAGE_DIR=str(storage), CHROMA_PATH=str(storage / 'chroma'), LLM_API_KEY='')

import uvicorn
from playwright.sync_api import sync_playwright
from app.main import app
from app.services.public_curriculum import public_curriculum

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
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{port}/')
        page.locator('#curriculum-stats').filter(has_text='60 节课程').wait_for()
        for lesson in public_curriculum()['lessons']:
            page.locator('#lesson-search').fill(lesson['title'])
            page.get_by_role('button', name=f'查看本节：{lesson["title"]}', exact=True).click()
            assert page.locator('#lesson-title').inner_text() == lesson['title']
            cards = page.locator('.knowledge-note')
            assert cards.count() == 2
            for index, point in enumerate(lesson['knowledge_points']):
                card = cards.nth(index)
                assert card.get_attribute('id') == f'knowledge-point-{point["id"]}'
                assert card.locator('.study-essentials li').count() == 3
                assert card.locator('.flow-nodes li').count() == 5
                deeper = card.locator('.study-deeper')
                assert not deeper.evaluate('(el) => el.open')
                deeper.locator('summary').click()
                assert deeper.locator('.teaching-section').first.is_visible()
                assert '边界' in deeper.inner_text()
                assert '误区' in deeper.inner_text()
                deeper.locator('summary').click()
            if lesson['id'] in {101, 128, 142, 160}:
                page.set_viewport_size({'width': 375, 'height': 812})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert cards.first.locator('.flow-nodes').evaluate('(el) => getComputedStyle(el).gridTemplateColumns.split(" ").length === 1')
                page.screenshot(path=str(storage / f'lesson-{lesson["id"]}-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('#back-catalog').click()
        page.locator('#lesson-search').fill('不会存在的课程名字')
        page.locator('#catalog').filter(has_text='没有匹配的课程').wait_for()
        page.locator('#lesson-search').fill('从用户问题到 AI 产品机会')
        page.get_by_role('button', name='查看本节：从用户问题到 AI 产品机会', exact=True).click()
        page.locator('#start-practice').click()
        page.locator('#answer').fill('先观察客服查询三份政策的过程，记录耗时和返工原因，再与原流程比较是否减少重复工作。')
        page.locator('#submit-answer').click()
        page.locator('#feedback').filter(has_text='尚未完成评价 · 不计分').wait_for()
        assert page.locator('#submit-answer').is_enabled()
        page.locator('#review-knowledge').click()
        assert page.locator('.study-essentials').count() == 2
        page.get_by_role('button', name='概念地图', exact=True).click()
        page.locator('#concept-search').fill('RAG')
        page.locator('.concept-card').first.wait_for()
        assert not errors, errors
        browser.close()
    print(json.dumps({'result': 'passed', 'lessons': 60, 'points': 120,
                      'checks': ['all-readers', 'closed-default', 'expand-collapse', 'mobile-four-topics', 'empty-search', 'offline-practice-and-return', 'concept-regression'],
                      'evidence': str(storage)}, ensure_ascii=False))
finally:
    server.should_exit = True
    thread.join(timeout=10)
