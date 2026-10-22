/* Local checkpoint/draft persistence. No keys, model calls or mastery updates. */
const learningProgress = (() => {
  let data = null;
  let view = 'catalog';
  let restoring = false;
  let checkpointTimer, draftTimer;
  let pendingCheckpoint = null, pendingDraft = null;
  let writingCheckpoint = Promise.resolve(), writingDraft = Promise.resolve();
  const labels = { not_started: '未开始', reading: '阅读中', practice: '练习中', completed: '已完成学习流程' };
  const el = (selector) => document.querySelector(selector);
  const row = (id) => data?.lessons.find(item => item.lesson_id === id);

  function dashboard() {
    if (!data) return;
    const s = data.summary;
    el('#progress-summary').textContent = `已完成 ${s.completed_lessons} / ${s.total_lessons} 节 · 已读 ${s.read_points} 个知识点 · 已练习 ${s.practiced_points} 个知识点 · 掌握度 ${s.mastery_percent}%`;
    el('#course-progress').max = s.total_lessons;
    el('#course-progress').value = s.completed_lessons;
    for (const [selector, value] of [['#metric-read', s.read_points], ['#metric-practiced', s.practiced_points], ['#metric-mastery', `${s.mastery_percent}%`]]) {
      if (el(selector)) el(selector).textContent = value;
    }
    const last = data.last_resume;
    el('#resume-learning').disabled = !last && !state.catalog?.items?.[0]?.lessons.length;
    el('#resume-learning').textContent = last ? '继续学习' : '开始第一节';
    el('#resume-label').textContent = last ? '接着上次的进度' : '从一个好问题开始';
    el('#resume-title').textContent = last?.title || '为下一次面试，积累一次判断。';
    el('#resume-point').textContent = last ? `${last.view === 'reading' ? '阅读到' : '练习到'}：${last.point_name}` : '从用户问题出发，读懂知识，再用真实场景检验理解。';
  }

  async function refresh(render = false) {
    await Promise.all([writingCheckpoint.catch(() => {}), writingDraft.catch(() => {})]);
    data = await api('/progress');
    dashboard();
    if (render && state.catalog) renderCatalog(state.catalog);
  }

  function write(path, payload, statusSelector) {
    return api(path, { method: 'POST', body: JSON.stringify(payload), keepalive: true })
      .then(value => { if (statusSelector) el(statusSelector).textContent = '已保存到本机'; return value; })
      .catch(error => { if (statusSelector) el(statusSelector).textContent = `尚未保存，请保持页面打开并重试：${error.message}`; throw error; });
  }

  function flushCheckpoint() {
    clearTimeout(checkpointTimer);
    if (!pendingCheckpoint) return writingCheckpoint;
    const snapshot = pendingCheckpoint;
    pendingCheckpoint = null;
    writingCheckpoint = writingCheckpoint.catch(() => {}).then(() => write('/progress/checkpoint', snapshot, '#reading-save-status'));
    writingCheckpoint.catch(() => {});
    return writingCheckpoint;
  }

  function queueCheckpoint(payload) {
    pendingCheckpoint = payload;
    el('#reading-save-status').textContent = '正在保存学习位置…';
    clearTimeout(checkpointTimer);
    checkpointTimer = setTimeout(flushCheckpoint, 450);
  }

  function readingPosition() {
    if (view !== 'lesson' || restoring || !state.activeLesson || !el('#learn').classList.contains('active')) return;
    const cards = [...document.querySelectorAll('.knowledge-note')];
    const card = cards.filter(item => item.getBoundingClientRect().top < innerHeight * .45).at(-1) || cards[0];
    if (!card) return;
    const box = card.getBoundingClientRect();
    queueCheckpoint({ lesson_id: state.activeLesson.id, point_id: Number(card.id.replace('knowledge-point-', '')),
      position: Math.max(0, Math.min(1, -box.top / box.height)), view: 'reading' });
  }

  function flushDraft() {
    clearTimeout(draftTimer);
    if (!pendingDraft) return writingDraft;
    const snapshot = pendingDraft;
    pendingDraft = null;
    writingDraft = writingDraft.catch(() => {}).then(() => write('/progress/draft', snapshot, '#draft-save-status'));
    writingDraft.catch(() => {});
    return writingDraft;
  }

  function captureDraft() {
    if (view !== 'practice' || !state.attemptId || state.currentPractice?.evaluated) return;
    pendingDraft = { session_id: state.sessionId, attempt_id: state.attemptId, text: el('#answer').value };
    el('#draft-save-status').textContent = '正在保存草稿…';
    clearTimeout(draftTimer);
    draftTimer = setTimeout(flushDraft, 350);
  }

  function practiceShown(payload) {
    if (!payload.current_knowledge_point || !state.activeLesson) return;
    queueCheckpoint({ lesson_id: state.activeLesson.id, point_id: payload.current_knowledge_point.id, view: 'practice' });
    flushCheckpoint();
    el('#draft-save-status').textContent = payload.evaluated ? '已恢复历史评价，不会重复评分。' : payload.draft_answer ? '已恢复上次回答／草稿；尚未自动提交。' : '草稿自动保存到本机，不会自动提交评分。';
  }

  async function resumeLesson(lessonId, forcePractice = false) {
    const button = el('#resume-learning');
    button.disabled = true;
    el('#progress-message').textContent = '正在恢复学习位置…';
    try {
      await flushCheckpoint();
      await flushDraft();
      const saved = await api(`/progress/lessons/${lessonId}/resume`);
      let course, lesson;
      for (const candidate of state.catalog.items) {
        const found = candidate.lessons.find(item => item.id === lessonId);
        if (found) { course = candidate; lesson = found; break; }
      }
      if (!lesson) throw new Error('课程不在当前公开目录中。');
      restoring = true;
      if ((forcePractice || saved.view === 'practice') && saved.practice) displayQuestion(saved.practice);
      else {
        openLesson(course, lesson);
        await new Promise(resolve => requestAnimationFrame(resolve));
        const card = document.getElementById(`knowledge-point-${saved.point_id}`);
        if (card) window.scrollTo({ top: window.scrollY + card.getBoundingClientRect().top + saved.position * card.getBoundingClientRect().height, behavior: 'instant' });
      }
      el('#progress-message').textContent = '已恢复；没有生成新题或调用评分模型。';
    } catch (error) { el('#progress-message').textContent = `恢复失败：${error.message}。记录仍保留，可重试。`; throw error; }
    finally { restoring = false; button.disabled = false; }
  }

  function decorateLesson(parent, lesson) {
    const record = row(lesson.id);
    const status = document.createElement('p');
    status.className = `lesson-progress ${record?.status || 'not_started'}`;
    const label = document.createElement('span');
    label.className = 'lesson-state';
    label.textContent = labels[record?.status || 'not_started'];
    const counts = document.createElement('span');
    counts.textContent = `已读 ${record?.read_count || 0}/${lesson.knowledge_points.length} · 已练习 ${record?.practiced_count || 0}/${lesson.knowledge_points.length} · 掌握度 ${record?.mastery || 0}%`;
    status.append(label, counts);
    parent.append(status);
  }

  function readMarker(parent, point) {
    const lessonId = state.activeLesson.id;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'read-marker';
    let read = Boolean(row(lessonId)?.read_point_ids.includes(point.id));
    const paint = () => { button.textContent = read ? '✓ 已读 · 点击撤销' : '标记这个知识点已读'; button.setAttribute('aria-pressed', String(read)); };
    paint();
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await flushCheckpoint();
        await write('/progress/checkpoint', { lesson_id: lessonId, point_id: point.id, position: 0, view: 'reading', read: !read }, '#reading-save-status');
        read = !read; paint(); await refresh();
      } catch (_) { /* The inline save status explains failure; preserve marker until saved. */ }
      finally { button.disabled = false; }
    });
    parent.append(button);
  }

  function leavePage() {
    readingPosition();
    if (view === 'practice' && !state.currentPractice?.evaluated) captureDraft();
    for (const [path, payload] of [['/checkpoint', pendingCheckpoint], ['/draft', pendingDraft]]) {
      if (payload && navigator.sendBeacon) navigator.sendBeacon(`/api/progress${path}`, new Blob([JSON.stringify(payload)], { type: 'application/json' }));
    }
  }

  async function init() {
    el('#resume-learning').addEventListener('click', () => {
      if (data?.last_resume) resumeLesson(data.last_resume.lesson_id).catch(() => {});
      else {
        const course = state.catalog?.items?.[0];
        if (course?.lessons[0]) openLesson(course, course.lessons[0]);
      }
    });
    el('#answer').addEventListener('input', captureDraft);
    window.addEventListener('scroll', readingPosition, { passive: true });
    window.addEventListener('pagehide', leavePage);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') { readingPosition(); flushCheckpoint(); flushDraft(); } });
    await refresh(true);
  }

  return { init, refresh, dashboard, decorateLesson, readMarker, resumeLesson,
    hasActive: (id) => Boolean(row(id)?.session_id),
    viewChanged(next) { if (view === 'lesson') flushCheckpoint(); if (view === 'practice') flushDraft(); view = next;
      if (next === 'lesson' && !restoring && state.activeLesson) queueCheckpoint({ lesson_id: state.activeLesson.id, point_id: state.activeLesson.knowledge_points[0].id, position: 0, view: 'reading' }); },
    beforeLessonOpen() { flushCheckpoint(); flushDraft(); }, practiceShown, beforeSubmit: flushDraft,
    async answerHandled(result) { clearTimeout(draftTimer); pendingDraft = null; state.currentPractice.evaluated = !isUnassessed(result) && !result.next_question; el('#answer').readOnly = state.currentPractice.evaluated;
      el('#draft-save-status').textContent = isUnassessed(result) ? '回答已保存，等待模型评价。' : '回答与评价已保存。';
      await refresh().catch(error => { el('#progress-message').textContent = `进度显示暂未更新：${error.message}。回答记录仍已保存。`; }); },
  };
})();
