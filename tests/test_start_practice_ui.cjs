const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function fixture(fetchImpl) {
  const elements = new Map();
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      textContent: '', hidden: true, disabled: false,
      classList: { add() {}, remove() {} },
      setAttribute() {}, removeAttribute() {}, scrollIntoView() {},
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: { querySelector: element }, fetch: fetchImpl,
    setTimeout, clearTimeout, AbortController,
  });
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  vm.runInContext(source.slice(0, source.indexOf('function initializeConcepts')), context);
  vm.runInContext("state.activeLesson = {id: 105}; displayQuestion = (data) => { globalThis.started = data; };", context);
  return { context, element, run: () => vm.runInContext('startPractice()', context) };
}

test('API preserves JSON content type together with local settings token', async () => {
  let captured;
  const f = fixture(async (_url, options) => {
    captured = options;
    return { ok: true, json: async () => ({ configured: true }) };
  });
  await vm.runInContext("api('/model-settings', {method: 'PUT', headers: {'X-Local-Settings-Token': 'test-token'}, body: '{}'})", f.context);
  assert.equal(captured.headers['Content-Type'], 'application/json');
  assert.equal(captured.headers['X-Local-Settings-Token'], 'test-token');
});

test('start shows loading immediately and ignores duplicate clicks', async () => {
  let resolveRequest;
  let requests = 0;
  const response = new Promise(resolve => { resolveRequest = resolve; });
  const f = fixture(() => { requests++; return response; });
  const pending = f.run();
  const duplicate = f.run();
  const disabledWhilePending = f.element('#start-practice').disabled;
  const messageWhilePending = f.element('#practice-status').textContent;
  resolveRequest({ ok: true, json: async () => ({ session_id: 123 }) });
  await Promise.all([pending, duplicate]);
  assert.equal(disabledWhilePending, true);
  assert.match(messageWhilePending, /准备/);
  assert.equal(requests, 1);
  assert.equal(f.context.started.session_id, 123);
  assert.equal(f.element('#start-practice').disabled, false);
});

test('disconnected service reports error beside the button and permits retry', async () => {
  const f = fixture(async () => { throw new TypeError('Failed to fetch'); });
  await f.run();
  assert.equal(f.element('#practice-status').hidden, false);
  assert.match(f.element('#practice-status').textContent, /无法连接.*启动/);
  assert.equal(f.element('#start-practice').disabled, false);
  assert.equal(f.element('#start-practice').textContent, '开始练习');
});

test('API error is visible next to the start button', async () => {
  const f = fixture(async () => ({ ok: false, status: 503, json: async () => ({ detail: '练习暂时不可用' }) }));
  await f.run();
  assert.equal(f.element('#practice-status').hidden, false);
  assert.match(f.element('#practice-status').textContent, /练习暂时不可用/);
  assert.equal(f.element('#start-practice').disabled, false);
});

test('a stalled request times out visibly and resets loading', async () => {
  const timers = new Map();
  const f = fixture((url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    });
  }));
  f.context.setTimeout = (callback, delay) => { timers.set(delay, callback); return delay; };
  f.context.clearTimeout = (delay) => timers.delete(delay);
  const pending = f.run();
  timers.get(60000)();
  await pending;
  assert.match(f.element('#practice-status').textContent, /超过 60 秒/);
  assert.equal(f.element('#practice-status').hidden, false);
  assert.equal(f.element('#start-practice').disabled, false);
  assert.equal(timers.size, 0);
});

test('null or missing score is unassessed even without new API metadata', () => {
  const f = fixture(async () => {});
  assert.equal(vm.runInContext('isUnassessed({total_score: null})', f.context), true);
  assert.equal(vm.runInContext('isUnassessed({})', f.context), true);
  assert.equal(vm.runInContext('isUnassessed({total_score: 0})', f.context), false);
  assert.equal(vm.runInContext('isUnassessed({total_score: 80})', f.context), false);
  assert.equal(vm.runInContext('isUnassessed({total_score: 80, evaluation_source: "offline"})', f.context), true);
});
