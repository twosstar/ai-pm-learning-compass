const $ = (selector) => document.querySelector(selector);
const state = {
  sessionId: null,
  attemptId: null,
  activeLesson: null,
  currentPractice: null,
  catalog: null,
  concepts: [],
  conceptCategories: [],
  conceptCategory: "",
  conceptPage: 1,
  openModules: new Set(),
  modulesTouched: false,
  startingPractice: false,
  targetRole: "general_ai_pm",
  modelSettingsToken: "",
  panelScroll: {},
};
const CONCEPT_PAGE_SIZE = 24;
const MODEL_PRESETS = {
  deepseek: { baseUrl: "https://api.deepseek.com", model: "deepseek-flash" },
  qwen: { baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  openai: { baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini" },
  gemini: { baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/", model: "gemini-3.8-flash" },
};

async function api(path, options = {}) {
  const { headers = {}, ...requestOptions } = options;
  const response = await fetch(`/api${path}`, {
    ...requestOptions,
    headers: { "Content-Type": "application/json", ...headers },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `请求失败（${response.status}）`);
  return body;
}

function showError(error) {
  $("#status").textContent = error.message || "连接失败，请稍后重试。";
  $("#status").classList.add("error");
}

async function refreshModelStatus(populateForm = false) {
  const config = await api("/model-settings");
  state.modelSettingsToken = config.settings_token;
  $("#model-config-status").textContent = config.configured
    ? config.last_error || (config.verified ? "模型已响应 · 可评分" : "已配置 · 待首次调用验证")
    : "未配置模型 · 暂不评分";
  $("#clear-model-settings").disabled = !config.configured;
  if (populateForm) {
    const initialPreset = MODEL_PRESETS.deepseek;
    $("#model-base-url").value = config.base_url || initialPreset.baseUrl;
    $("#model-name").value = config.model || initialPreset.model;
    const provider = Object.entries(MODEL_PRESETS).find(([, preset]) =>
      preset.baseUrl.replace(/\/$/, "") === (config.base_url || "").replace(/\/$/, ""));
    $("#model-provider").value = config.configured ? (provider?.[0] || "custom") : "deepseek";
    $("#model-api-key").value = "";
    $("#model-consent").checked = false;
  }
  return config;
}

$("#model-provider").addEventListener?.("change", (event) => {
  const preset = MODEL_PRESETS[event.target.value];
  if (!preset) return;
  $("#model-base-url").value = preset.baseUrl;
  $("#model-name").value = preset.model;
});

async function openModelSettings() {
  $("#model-settings-message").textContent = "正在读取本地配置状态…";
  $("#model-settings-dialog").showModal();
  try {
    const config = await refreshModelStatus(true);
    $("#model-settings-message").textContent = config.last_error || (config.configured
      ? "已启用。修改配置需要重新输入密钥，页面不会读取已有密钥。"
      : "尚未配置。填好并保存后，无需重启即可重新评价。保存本身不产生调用费用。");
  } catch (error) { $("#model-settings-message").textContent = error.message; }
}

function setView(view) {
  if (typeof learningProgress !== 'undefined') learningProgress.viewChanged(view);
  $("#catalog-view").hidden = view !== "catalog";
  $("#lesson-view").hidden = view !== "lesson";
  $("#session").hidden = view !== "practice";
}

function renderModuleShortcuts(data) {
  const shortcuts = $("#module-shortcuts");
  if (!shortcuts) return;
  shortcuts.replaceChildren();
  for (const module of data.modules || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "module-shortcut";
    button.setAttribute("aria-controls", `module-${module.id}`);
    const number = document.createElement("span");
    number.textContent = String(module.order).padStart(2, "0");
    const name = document.createElement("span");
    name.textContent = module.label;
    button.append(number, name);
    button.title = module.label;
    button.addEventListener("click", () => {
      $("#lesson-search").value = "";
      state.modulesTouched = true;
      state.openModules.add(module.id);
      document.querySelector('.tab[data-panel="learn"]').click();
      setView("catalog");
      renderCatalog(data);
      const chapter = document.getElementById(`module-${module.id}`);
      if (chapter) {
        chapter.open = true;
        chapter.scrollIntoView({ behavior: "smooth", block: "start" });
        chapter.querySelector("summary").focus({ preventScroll: true });
      }
    });
    shortcuts.append(button);
  }
}

function renderCatalog(data) {
  state.catalog = data;
  renderModuleShortcuts(data);
  if (typeof learningProgress !== 'undefined') learningProgress.dashboard();
  const term = $("#lesson-search").value.trim().toLocaleLowerCase();
  $("#curriculum-stats").textContent = `${data.total_lessons} 节课程 · ${data.modules?.length || 0} 个模块 · ${data.total_knowledge_points} 个知识点`;
  $("#curriculum-basis").textContent = `${data.textbook_lessons} 节有可阅读教材章节依据，其余基于公开指南、作者摘要或权威工程资料。${data.editorial_note || ""}`;
  const outlines = $("#curriculum-outlines");
  outlines.replaceChildren();
  for (const source of data.outline_sources || []) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.textContent = source.title;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const usage = document.createElement("span");
    usage.textContent = ` — ${source.usage}`;
    item.append(link, usage);
    outlines.append(item);
  }
  const root = $("#catalog");
  root.replaceChildren();
  let visibleLessons = 0;
  for (const course of data.items || []) {
    const group = document.createElement("article");
    group.className = "course-card";
    const heading = document.createElement("div");
    heading.className = "course-heading";
    const title = document.createElement("h3");
    title.textContent = course.name;
    const lessonCount = document.createElement("span");
    lessonCount.className = "course-count";
    lessonCount.textContent = `${course.lessons.length} 节课程`;
    heading.append(title, lessonCount);
    group.append(heading);
    for (const [moduleIndex, module] of (data.modules || []).entries()) {
      const members = course.lessons.filter((lesson) => lesson.module_id === module.id && (
        !term || [lesson.title, lesson.section, lesson.summary, ...(lesson.knowledge_points || []).map((point) => point.name)].join(" ").toLocaleLowerCase().includes(term)
      ));
      if (!members.length) continue;
      visibleLessons += members.length;
      const chapter = document.createElement("details");
      chapter.className = "course-module";
      chapter.id = `module-${module.id}`;
      chapter.dataset.module = module.id;
      chapter.open = Boolean(term) || state.openModules.has(module.id) || (moduleIndex === 0 && !state.modulesTouched);
      chapter.addEventListener("toggle", () => {
        state.modulesTouched = true;
        if (chapter.open) state.openModules.add(module.id);
        else state.openModules.delete(module.id);
      });
      const moduleHeading = document.createElement("summary");
      const moduleNumber = document.createElement("span");
      moduleNumber.className = "module-number";
      moduleNumber.textContent = String(module.order).padStart(2, "0");
      const moduleName = document.createElement("span");
      moduleName.className = "module-name";
      moduleName.textContent = module.label;
      const moduleCount = document.createElement("span");
      moduleCount.className = "module-count";
      moduleCount.textContent = `${members.length} 节`;
      moduleHeading.append(moduleNumber, moduleName, moduleCount);
      chapter.append(moduleHeading);
      for (const lesson of members) {
        const row = document.createElement("article");
        row.className = "lesson-row";
        const indexLabel = document.createElement("span");
        indexLabel.className = "lesson-index";
        indexLabel.textContent = String(lesson.number).padStart(2, "0");
        const detail = document.createElement("div");
        detail.className = "lesson-row-content";
        const lessonTitle = document.createElement("h4");
        lessonTitle.textContent = lesson.title;
        const meta = document.createElement("p");
        meta.className = "muted";
        const pointNames = (lesson.knowledge_points || []).map((point) => point.name);
        meta.textContent = pointNames.join(" / ");
        detail.append(lessonTitle, meta);
        if (typeof learningProgress !== 'undefined') learningProgress.decorateLesson(detail, lesson);
        const button = document.createElement("button");
        button.className = "outline-button";
        button.textContent = "查看本节";
        button.setAttribute("aria-label", `查看本节：${lesson.title}`);
        button.addEventListener("click", () => openLesson(course, lesson));
        row.append(indexLabel, detail, button);
        chapter.append(row);
      }
      group.append(chapter);
    }
    root.append(group);
  }
  $("#lesson-match-count").textContent = term ? `找到 ${visibleLessons} 节匹配课程` : "按模块展开，选择本节后先学习知识点，再进入岗位情境练习。";
  if (!visibleLessons) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "没有匹配的课程，试试“检索”“微调”或清除搜索。";
    root.append(empty);
  }
}

function addReadingBlock(parent, label, text, className = "") {
  if (!text) return;
  const block = document.createElement("section");
  block.className = `reading-block ${className}`.trim();
  const heading = document.createElement("h5");
  heading.textContent = label;
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  block.append(heading, paragraph);
  parent.append(block);
}

function renderQuickStudy(card, quick) {
  const essentials = document.createElement("ul");
  essentials.className = "study-essentials";
  for (const text of quick.essentials || []) {
    const item = document.createElement("li");
    item.textContent = text;
    essentials.append(item);
  }
  const figure = document.createElement("figure");
  figure.className = "study-flow";
  const caption = document.createElement("figcaption");
  caption.textContent = quick.flow_title;
  const nodes = document.createElement("ol");
  nodes.className = "flow-nodes";
  for (const node of quick.flow || []) {
    const item = document.createElement("li");
    const owner = document.createElement("small");
    owner.textContent = node.owner;
    const label = document.createElement("span");
    label.textContent = node.label;
    item.append(owner, label);
    nodes.append(item);
  }
  figure.append(caption, nodes);
  for (const branch of quick.branches || []) {
    const p = document.createElement("p");
    p.className = "flow-branch";
    p.textContent = branch;
    figure.append(p);
  }
  const example = document.createElement("p");
  example.className = "study-mini-example";
  example.textContent = `一个例子：${quick.example}`;
  const interview = document.createElement("p");
  interview.className = "study-interview";
  interview.textContent = quick.interview;
  card.append(essentials, figure, example, interview);
}

function openLesson(course, lesson) {
  if (typeof learningProgress !== 'undefined') learningProgress.beforeLessonOpen();
  state.activeLesson = { ...lesson, course_name: course.name };
  const pointList = lesson.knowledge_points || [];
  $("#lesson-section").textContent = `${course.name} / ${lesson.section || "学习章节"}`;
  $("#lesson-title").textContent = lesson.title;
  $("#lesson-summary").textContent = lesson.summary || "本节摘要暂缺，先从下面的知识点开始。";
  $("#knowledge-point-count").textContent = `${pointList.length} 个知识点`;
  const objectives = $("#lesson-objectives");
  objectives.replaceChildren();
  for (const objective of lesson.objectives || []) {
    const item = document.createElement("li");
    item.textContent = objective;
    objectives.append(item);
  }
  $("#lesson-practice-task").textContent = lesson.practice_task || "";

  const nav = $("#knowledge-point-nav");
  const content = $("#knowledge-point-list");
  nav.replaceChildren();
  content.replaceChildren();

  pointList.forEach((point, index) => {
    const link = document.createElement("a");
    link.href = `#knowledge-point-${point.id}`;
    link.className = "outline-link";
    link.textContent = point.name;
    nav.append(link);

    const card = document.createElement("article");
    card.className = "knowledge-note";
    card.id = `knowledge-point-${point.id}`;
    const head = document.createElement("div");
    head.className = "knowledge-note-heading";
    const number = document.createElement("span");
    number.className = "knowledge-number";
    number.textContent = String(index + 1).padStart(2, "0");
    const titleWrap = document.createElement("div");
    const category = document.createElement("span");
    category.className = "knowledge-category";
    category.textContent = point.category || "核心知识";
    const title = document.createElement("h4");
    title.textContent = point.name;
    titleWrap.append(category, title);
    head.append(number, titleWrap);
    card.append(head);
    if (point.teaching_sections?.length) {
      card.classList.add("expanded-teaching");
      let detailTarget = card;
      if (point.quick_study) {
        renderQuickStudy(card, point.quick_study);
        const deeper = document.createElement("details");
        deeper.className = "study-deeper";
        const summary = document.createElement("summary");
        summary.textContent = "按需深入：完整案例、反例与操作细节";
        deeper.append(summary);
        card.append(deeper);
        detailTarget = deeper;
      }
      for (const section of point.teaching_sections) {
        const block = document.createElement("section");
        block.className = "teaching-section";
        const heading = document.createElement("h5");
        heading.textContent = section.title;
        block.append(heading);
        for (const paragraph of section.paragraphs || []) {
          const p = document.createElement("p");
          p.textContent = paragraph;
          block.append(p);
        }
        if (section.steps?.length) {
          const list = document.createElement("ol");
          for (const step of section.steps) {
            const item = document.createElement("li");
            item.textContent = step;
            list.append(item);
          }
          block.append(list);
        }
        detailTarget.append(block);
      }
    } else {
      addReadingBlock(card, "原理与机制", point.core_explanation || point.description);
      addReadingBlock(card, "为什么重要", point.why_explanation);
      addReadingBlock(card, "原创教学例子", point.teaching_example, "example-block");
      addReadingBlock(card, "AI PM 迁移", point.ai_pm_relevance, "relevance-block");
    }
    if (point.mastery > 0) {
      const mastery = document.createElement("p");
      mastery.className = "mastery-note";
      mastery.textContent = `当前掌握度 ${point.mastery}%`;
      card.append(mastery);
    }
    if (typeof learningProgress !== 'undefined') learningProgress.readMarker(card, point);
    content.append(card);
  });

  const hasCurrentPractice = state.currentPractice?.lesson_id === lesson.id;
  $("#start-practice").textContent = hasCurrentPractice ? "回到当前练习" : "开始练习";
  setView("lesson");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function displayQuestion(payload) {
  if (payload.lesson_id && state.catalog) {
    for (const course of state.catalog.items || []) {
      const lesson = course.lessons.find((item) => item.id === payload.lesson_id);
      if (lesson) {
        state.activeLesson = { ...lesson, course_name: course.name };
        break;
      }
    }
  }
  state.sessionId = payload.session_id;
  state.attemptId = payload.question_attempt_id;
  state.currentPractice = {
    ...payload,
    lesson_id: payload.lesson_id ?? state.activeLesson?.id,
    target_role: payload.question?.target_role || state.targetRole,
  };
  const section = state.activeLesson?.section || "学习路径";
  $("#lesson-label").textContent = `${section} / ${payload.lesson_title}`;
  $("#point-title").textContent = payload.current_knowledge_point?.name || "当前知识点";
  $("#teaching").textContent = payload.current_knowledge_point?.core_explanation || payload.course_summary || "";
  $("#question-type").textContent = payload.question?.question_type || "学习问题";
  $("#question").textContent = payload.question?.question || "";
  renderQuestionCareer(payload.question);
  $("#answer").value = payload.draft_answer || "";
  $("#answer").readOnly = Boolean(payload.evaluated);
  $("#submit-answer").textContent = "提交并查看反馈";
  $("#feedback").hidden = true;
  $("#next").hidden = true;
  $("#submit-answer").disabled = false;
  if (payload.saved_feedback) renderAnswerFeedback(payload.saved_feedback, payload.question);
  $("#submit-answer").disabled = Boolean(payload.evaluated);
  $("#next").hidden = !payload.can_continue;
  setView("practice");
  if (typeof learningProgress !== 'undefined') learningProgress.practiceShown(payload);
  $("#session").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function startPractice() {
  if (!state.activeLesson || state.startingPractice) return;
  if (state.currentPractice?.lesson_id === state.activeLesson.id) {
    setView("practice");
    $("#session").scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const button = $("#start-practice");
  if (typeof learningProgress !== 'undefined' && learningProgress.hasActive(state.activeLesson.id)) {
    state.startingPractice = true;
    try { await learningProgress.resumeLesson(state.activeLesson.id, true); }
    catch (error) { showError(error); }
    finally { state.startingPractice = false; }
    return;
  }
  const status = $("#practice-status");
  const lessonId = state.activeLesson.id;
  const controller = new AbortController();
  state.startingPractice = true;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "正在准备练习…";
  status.hidden = false;
  status.classList.remove("error");
  status.textContent = "正在准备本节练习，请稍候；模型出题可能需要一些时间。";
  const waiting = setTimeout(() => {
    status.textContent = "仍在等待练习结果，请勿重复点击。若长时间无结果，会在这里提示。";
  }, 10000);
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    displayQuestion(await api("/study/start", {
      method: "POST",
      body: JSON.stringify({ lesson_id: lessonId, target_role: state.targetRole }),
      signal: controller.signal,
    }));
    status.hidden = true;
    $("#status").textContent = "本地学习服务已连接";
    $("#status").classList.remove("error");
  } catch (error) {
    const message = error.name === "AbortError"
      ? "等待练习超过 60 秒。请检查模型服务连接；请求可能仍在处理，请稍后再试。"
      : error.name === "TypeError"
        ? "无法连接本地学习服务。请先双击 Start Learning Copilot.bat 启动服务，并保持启动窗口开启，再试一次。"
        : `练习启动失败：${error.message || "未知错误"}。请检查后重试。`;
    status.textContent = message;
    status.hidden = false;
    status.classList.add("error");
    showError(new Error(message));
  } finally {
    clearTimeout(waiting);
    clearTimeout(timeout);
    state.startingPractice = false;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = state.currentPractice?.lesson_id === state.activeLesson?.id ? "回到当前练习" : "开始练习";
  }
}

function renderQuestionCareer(question) {
  const roleNames = { general_ai_pm: "通用 AI 产品经理", ai_education_pm: "AI+教育产品经理" };
  $("#question-career").hidden = !question;
  if (!question) return;
  $("#question-career-meta").textContent = `${roleNames[question.target_role] || "AI 产品经理"} · ${question.interview_depth || "P1"} · 练习难度 ${question.difficulty || 1}`;
  $("#question-career-why").textContent = `面试官为什么问：${question.why_interviewer_asks || "考察能否形成有依据的产品判断。"}`;
  $("#question-career-boundary").textContent = question.unnecessary_detail || "不必追求术语复述，请讲清取舍和原因。";
}

function isUnassessed(result) {
  return result?.evaluation_source === "offline" || result?.pass_status === "UNASSESSED" || !Number.isFinite(result?.total_score);
}

function renderAnswerFeedback(result, submittedQuestion) {
  const root = $("#feedback");
  root.replaceChildren();
  const offline = isUnassessed(result);
  const text = (parent, tag, value, className = "") => {
    if (!value) return;
    const node = document.createElement(tag);
    node.textContent = value;
    node.className = className;
    parent.append(node);
  };
  const list = (parent, title, items, ordered = false) => {
    if (!items?.length) return;
    text(parent, "h4", title);
    const node = document.createElement(ordered ? "ol" : "ul");
    for (const item of items) text(node, "li", item);
    parent.append(node);
  };
  text(root, "strong", offline ? "尚未完成评价 · 不计分" : `${result.total_score} 分 · ${result.pass_label}`, "score");
  text(root, "p", result.score_explanation);
  if (result.next_question) text(root, "p", "上方已切换为巩固题；以下反馈对应刚刚提交的题目。", "feedback-context-note");
  const context = document.createElement("details");
  context.className = "feedback-context";
  text(context, "summary", "本次问题与我的回答");
  text(context, "h4", "本次问题");
  text(context, "p", result.evaluated_question || submittedQuestion?.question || "");
  text(context, "h4", "我的回答");
  text(context, "p", result.user_answer);
  root.append(context);
  if (!offline) {
    list(root, "你已经答对", result.correct_points?.slice(0, 3));
    const gaps = result.key_gaps?.slice(0, 2) || [];
    if (gaps.length) {
      text(root, "h4", "最需要补充");
      for (const gap of gaps) {
        const block = document.createElement("section");
        block.className = "feedback-gap";
        text(block, "strong", gap.point);
        text(block, "p", gap.why_it_matters);
        text(block, "p", `补充方向：${gap.direction}`);
        root.append(block);
      }
    } else list(root, "最需要补充", result.missing_points?.slice(0, 2));
  }
  const reference = offline ? result.expert_answer : result.improved_answer || result.expert_answer;
  if (reference) {
    const panel = document.createElement("section");
    panel.className = "feedback-reference";
    text(panel, "h4", offline ? "本题参考答案（未作个人评价）" : "优化答案");
    text(panel, "p", reference);
    root.append(panel);
  }
  const more = document.createElement("details");
  more.className = "feedback-more";
  text(more, "summary", offline ? "查看本题答题主干" : "更多反馈：答题主干、专家答案与分项评分");
  list(more, "答题主干", result.answer_framework, true);
  if (!offline && result.expert_answer && result.expert_answer !== reference) {
    text(more, "h4", "专家答案");
    text(more, "p", result.expert_answer);
  }
  if (!offline && result.dimensions) {
    const names = { concept_accuracy: "概念准确", technical_understanding: "机制理解", product_thinking: "产品判断", application_scenario: "场景应用", communication_structure: "表达结构" };
    list(more, "分项评分", Object.entries(names).map(([key, label]) => `${label}：${result.dimensions[key]} / 20`));
    list(more, "其他待复习", result.key_gaps?.slice(2).map(gap => `${gap.point}：${gap.direction}`));
  }
  if (more.children.length > 1) root.append(more);
  if (!offline) text(root, "p", result.interview_message, "feedback-progress");
  root.hidden = false;
}

function initializeConcepts(data) {
  state.concepts = data.items || [];
  state.conceptCategories = data.categories || [];
  $("#concept-total").textContent = `${data.total} 个概念 · ${state.conceptCategories.length} 个主题`;
  const filters = $("#concept-categories");
  filters.replaceChildren();
  const categories = [{ id: "", label: "全部", count: data.total }, ...state.conceptCategories];
  for (const category of categories) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.category = category.id;
    button.textContent = `${category.label} ${category.count}`;
    button.addEventListener("click", () => {
      state.conceptCategory = category.id;
      state.conceptPage = 1;
      renderConcepts();
    });
    filters.append(button);
  }
  renderConcepts();
}

function renderConcepts() {
  const term = $("#concept-search").value.trim().toLocaleLowerCase();
  const items = state.concepts.filter((item) => {
    const haystack = [item.name, ...(item.aliases || []), item.category_label, item.definition, item.mechanism].join(" ").toLocaleLowerCase();
    return (!state.conceptCategory || item.category === state.conceptCategory) && (!term || haystack.includes(term));
  });
  if (term) {
    const exactMatch = (item) => [item.name, ...(item.aliases || [])].some((name) => name.toLocaleLowerCase() === term);
    items.sort((a, b) => Number(exactMatch(b)) - Number(exactMatch(a)));
  }
  const pages = Math.max(1, Math.ceil(items.length / CONCEPT_PAGE_SIZE));
  state.conceptPage = Math.min(state.conceptPage, pages);
  const start = (state.conceptPage - 1) * CONCEPT_PAGE_SIZE;
  $("#concept-result-count").textContent = items.length
    ? `找到 ${items.length} 个概念，当前显示 ${start + 1}–${Math.min(start + CONCEPT_PAGE_SIZE, items.length)} 个`
    : "没有匹配的概念，试试其他中文、英文或缩写。";
  $("#concept-page").textContent = `第 ${state.conceptPage} / ${pages} 页`;
  $("#concept-prev").disabled = state.conceptPage <= 1;
  $("#concept-next").disabled = state.conceptPage >= pages;
  document.querySelectorAll("#concept-categories button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.category === state.conceptCategory));
  });
  const root = $("#concept-list");
  root.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "concept-empty";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "清除搜索与筛选";
    reset.addEventListener("click", () => {
      $("#concept-search").value = "";
      state.conceptCategory = "";
      state.conceptPage = 1;
      renderConcepts();
      $("#concept-search").focus();
    });
    empty.append(reset);
    root.append(empty);
  }
  for (const concept of items.slice(start, start + CONCEPT_PAGE_SIZE)) {
    const card = document.createElement("article");
    card.className = "concept-card";
    const category = document.createElement("span");
    category.className = "badge";
    category.textContent = concept.category_label || concept.category;
    const priorityLabels = { CORE: "核心概念", IMPORTANT: "重要概念", SUPPLEMENTARY: "补充概念" };
    const priority = document.createElement("span");
    priority.className = `badge concept-priority ${concept.priority || ""}`;
    priority.textContent = priorityLabels[concept.priority] || "";
    const title = document.createElement("h3");
    title.textContent = concept.name;
    const english = document.createElement("p");
    english.className = "concept-alias";
    english.textContent = (concept.aliases || []).slice(0, 2).join(" · ");
    const description = document.createElement("p");
    description.textContent = concept.definition;
    const details = document.createElement("details");
    details.open = concept.name === "检索增强生成";
    const summary = document.createElement("summary");
    summary.textContent = "查看应用方法与边界";
    details.append(summary);
    addReadingBlock(details, "它如何运作", concept.mechanism);
    addReadingBlock(details, "适用场景 / 什么时候用", concept.when_to_use);
    addReadingBlock(details, "典型业务场景", concept.typical_scenario || concept.example, "concept-example");
    addReadingBlock(details, "不适用边界 / 容易误用", concept.when_not_to_use);
    addReadingBlock(details, "AI PM 怎么判断", concept.ai_pm_relevance);
    if (concept.interview_questions?.length) {
      const interview = document.createElement("div");
      interview.className = "concept-interview";
      const heading = document.createElement("h4");
      heading.textContent = "面试常问";
      interview.append(heading);
      const list = document.createElement("ul");
      for (const question of concept.interview_questions) {
        const item = document.createElement("li");
        item.textContent = question;
        list.append(item);
      }
      interview.append(list);
      details.append(interview);
    }
    const related = document.createElement("div");
    related.className = "concept-related";
    const relatedLabel = document.createElement("p");
    relatedLabel.textContent = "同主题继续阅读";
    related.append(relatedLabel);
    for (const name of concept.related_names || []) {
      const link = document.createElement("button");
      link.type = "button";
      link.textContent = name;
      link.addEventListener("click", () => {
        $("#concept-search").value = name;
        state.conceptCategory = "";
        state.conceptPage = 1;
        renderConcepts();
        $("#concepts").scrollIntoView({ behavior: "smooth" });
      });
      related.append(link);
    }
    if (concept.related_names?.length) details.append(related);
    const sources = document.createElement("div");
    sources.className = "concept-sources";
    const sourceLabel = document.createElement("p");
    sourceLabel.textContent = "参考阅读（英文）";
    sources.append(sourceLabel);
    for (const source of concept.sources || []) {
      const link = document.createElement("a");
      link.href = source.url;
      link.textContent = source.title;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      sources.append(link);
    }
    if (concept.sources?.length) details.append(sources);
    card.append(category);
    if (priority.textContent) card.append(priority);
    card.append(title, english, description, details);
    root.append(card);
  }
}

$("#answer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#submit-answer");
  const submittedQuestion = state.currentPractice?.question;
  button.disabled = true;
  try {
    if (typeof learningProgress !== 'undefined') await learningProgress.beforeSubmit();
    const result = await api("/study/answer", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        question_attempt_id: state.attemptId,
        answer: $("#answer").value,
      }),
    });
    renderAnswerFeedback(result, submittedQuestion);
    refreshModelStatus().catch(() => {});
    if (result.next_action === "retry_evaluation" || isUnassessed(result)) {
      button.textContent = "重新评价（保留原回答）";
      button.disabled = false;
      $("#next").hidden = true;
      if (typeof learningProgress !== 'undefined') await learningProgress.answerHandled(result);
      return;
    }
    if (result.next_question && result.next_attempt_id) {
      state.attemptId = result.next_attempt_id;
      state.currentPractice = {
        ...state.currentPractice,
        question_attempt_id: result.next_attempt_id,
        question: result.next_question,
      };
      $("#question-type").textContent = result.next_question.question_type || "巩固问题";
      $("#question").textContent = result.next_question.question || "";
      renderQuestionCareer(result.next_question);
      $("#answer").value = "";
      button.textContent = "提交巩固回答";
      button.disabled = false;
      $("#next").hidden = true;
    } else {
      const canContinue = ["advance", "interview_ready", "needs_review", "defer_and_continue", "complete"].includes(result.next_action);
      $("#next").hidden = !canContinue;
      if (result.next_action === "complete") $("#next").textContent = "完成本节";
    }
    if (typeof learningProgress !== 'undefined') await learningProgress.answerHandled(result);
  } catch (error) { showError(error); button.disabled = false; }
});

$("#next").addEventListener("click", async () => {
  try {
    const result = await api("/study/continue", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    if (result.completed) {
      $("#feedback").insertAdjacentText("beforeend", " 本节已完成，学习进度已保存。");
      $("#next").hidden = true;
      renderCatalog(await api("/catalog"));
      return;
    }
    renderCatalog(await api("/catalog"));
    if (typeof learningProgress !== 'undefined') await learningProgress.refresh(true);
    const nextLesson = result.lesson_id && result.lesson_id !== state.activeLesson?.id;
    displayQuestion(result);
    if (nextLesson && state.activeLesson) {
      openLesson({ name: state.activeLesson.course_name }, state.activeLesson);
    }
  } catch (error) { showError(error); }
});

$("#back-catalog").addEventListener("click", () => {
  setView("catalog");
  if (typeof learningProgress !== 'undefined') learningProgress.refresh(true).catch(showError);
  window.scrollTo({ top: 0, behavior: "smooth" });
});
$("#lesson-search").addEventListener("input", () => {
  if (state.catalog) renderCatalog(state.catalog);
});
$("#start-practice").addEventListener("click", startPractice);
$("#open-model-settings").addEventListener("click", openModelSettings);
$("#close-model-settings").addEventListener("click", () => $("#model-settings-dialog").close());
$("#model-settings-dialog").addEventListener("close", () => { $("#model-api-key").value = ""; });
$("#model-settings-dialog").addEventListener("cancel", () => { $("#model-api-key").value = ""; });
$("#model-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const save = $("#save-model-settings");
  save.disabled = true;
  $("#clear-model-settings").disabled = true;
  $("#model-settings-message").textContent = "正在保存到本次运行…";
  try {
    await api("/model-settings", {
      method: "PUT",
      headers: { "X-Local-Settings-Token": state.modelSettingsToken },
      body: JSON.stringify({ base_url: $("#model-base-url").value.trim(), model: $("#model-name").value.trim(),
        api_key: $("#model-api-key").value.trim(), allow_provider_requests: $("#model-consent").checked }),
    });
    $("#model-api-key").value = "";
    await refreshModelStatus();
    $("#model-settings-message").textContent = "已保存到本次运行内存；尚未调用供应商验证。关闭此窗口后可提交或重新评价，无需重启。";
  } catch (error) {
    $("#model-settings-message").textContent = error.message || "保存失败，请检查配置。";
    $("#model-api-key").value = "";
  } finally {
    save.disabled = false;
    refreshModelStatus().catch(() => {});
  }
});
$("#clear-model-settings").addEventListener("click", async () => {
  const button = $("#clear-model-settings");
  button.disabled = true;
  try {
    await api("/model-settings", { method: "DELETE", headers: { "X-Local-Settings-Token": state.modelSettingsToken } });
    $("#model-api-key").value = "";
    await refreshModelStatus();
    $("#model-settings-message").textContent = "当前运行配置已清除，后续请求不会使用该密钥。在途请求可能仍会完成；学习记录保留。";
  } catch (error) { $("#model-settings-message").textContent = error.message; button.disabled = false; }
});
try {
  const savedRole = localStorage.getItem("public-learning-target-role");
  if (["general_ai_pm", "ai_education_pm"].includes(savedRole)) state.targetRole = savedRole;
} catch (_) { /* The selector still works when local storage is unavailable. */ }
$("#career-role").value = state.targetRole;
$("#career-role").addEventListener("change", (event) => {
  state.targetRole = event.target.value;
  try { localStorage.setItem("public-learning-target-role", state.targetRole); } catch (_) { /* Optional preference only. */ }
});
$("#review-knowledge").addEventListener("click", () => {
  if (state.activeLesson) openLesson({ name: state.activeLesson.course_name }, state.activeLesson);
});
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  const previous = document.querySelector(".panel.active");
  if (previous) state.panelScroll[previous.id] = window.scrollY;
  document.querySelectorAll(".tab, .panel").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  button.classList.add("active");
  $(`#${button.dataset.panel}`).classList.add("active");
  if (button.dataset.view) setView(button.dataset.view);
  window.scrollTo({ top: state.panelScroll[button.dataset.panel] || 0, behavior: "instant" });
}));
document.querySelector("[data-open-concepts]").addEventListener("click", () => {
  document.querySelector('.tab[data-panel="concepts"]').click();
});
$("#concept-search").addEventListener("input", () => {
  state.conceptPage = 1;
  renderConcepts();
});
for (const [selector, step] of [["#concept-prev", -1], ["#concept-next", 1]]) {
  $(selector).addEventListener("click", () => {
    state.conceptPage += step;
    renderConcepts();
    $("#concepts").scrollIntoView({ behavior: "smooth" });
  });
}

Promise.all([api("/health"), api("/catalog"), api("/concepts")])
  .then(([, catalog, concepts]) => {
    $("#status").textContent = "本地学习服务已连接";
    renderCatalog(catalog);
    initializeConcepts(concepts);
    if (typeof learningProgress !== 'undefined') learningProgress.init().catch(error => { $("#progress-summary").textContent = `进度暂不可用：${error.message}。请重试刷新；原记录不会清除。`; });
  })
  .catch(showError);
refreshModelStatus().catch(() => { $("#model-config-status").textContent = "模型状态暂不可用，可打开设置重试"; });
