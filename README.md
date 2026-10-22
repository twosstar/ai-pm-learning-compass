# AI PM Learning Copilot — Public Edition

[中文项目介绍](docs/PROJECT_INTRO.zh-CN.md) · [English introduction](docs/PROJECT_INTRO.en.md) · [发布素材 / Launch kit](docs/LAUNCH_KIT.md)

![Local learning workspace with resumable progress](docs/images/learning-dashboard.png)

Screenshots use temporary demo records, not private learning data. The current UI/content are primarily Chinese; bilingual project introductions are provided.

An independent, local-first learning companion for AI product-management concepts. This first release contains only smart learning, a concept map, answer feedback, and locally persisted progress through a public sample path.

## Scope and content

The included sample curriculum and concept cards were written for this public edition. They are general educational examples, not reproductions of a paid course. The project does not include course videos, slides, handouts, transcripts, proprietary question banks, course captures, browser profiles, databases, or learning records from the private application.

The authoritative curriculum is `app/data/public_curriculum.json`: 60 lessons in 10 independently arranged modules, with 120 fixed knowledge points. It preserves the first three public lesson IDs (101–103) and six original public knowledge-point IDs (1001–1006). `sample_curriculum.json` remains only as the historical sample/ID reference. No private course outline or private database is imported.

46 lessons have publicly readable textbook chapter references; the other 14 identify guides, official documentation, research papers or author chapter summaries. Each lesson shows learning objectives, explanations, original business examples, and an original practice task before starting questions. Detailed lesson/knowledge-point source panels are not rendered in the reader; provenance remains in the curriculum JSON and API for maintenance. See `CURRICULUM_SOURCES.md` for source scope and limitations. Source links are references, not redistributed books or a claim of authorization to copy their prose.

## Features

- Smart learning along the included public path.
- Generated or fallback questions, answer evaluation, feedback, and remediation.
- Persistent attempts, mastery scores, and progress in a local SQLite database.
- A local concept map with 150 independently authored cards, 10 topic filters, Chinese/English search, examples, related reading, and reference links. Browsing does not call a model API.
- A continue action that advances to the next eligible knowledge point.

The public HTTP surface intentionally exposes only health, catalog, concept-map reads, and the learning start/answer/continue flow. Course collection, browser control, file import, interview practice, question-bank import, and V2 training are not mounted in this edition.

## Setup and launch

Requires Python 3.11 or later. On Windows, double-click `Start Learning Copilot.bat`. On first run it creates a local virtual environment and installs the app's dependencies; this can take a few minutes and requires an internet connection. It creates `.env` from `.env.example` only if `.env` does not already exist, then starts the app and opens the browser at <http://127.0.0.1:8001/>. Keep the console window open while using the app; press Ctrl+C in that window to stop it.

To enable scoring, open **模型设置** at the top of the page. Enter your trusted provider's HTTPS OpenAI-compatible API base URL, exact model name and your own key, acknowledge provider access/cost, then save. Saving performs no provider request and needs no restart. Start a practice or retry a pending evaluation to make the first real call. Never send keys in chat. If port 8001 is already occupied, close the other app and launch again.

The public edition does not inherit the original application's model key. Page-entered keys live only in the local server process: not in files, the learning database, localStorage or sessionStorage. They are not returned by the settings API. Password fields clear on save/close. Restarting the server requires re-entry. Clearing settings disables future calls; already in-flight requests may still complete. The settings API accepts loopback/same-origin access only and requires a process token for changes; provider URLs must use HTTPS without embedded credentials or query parameters. This is for trusted local use, not public multi-user hosting or an untrusted-device security boundary. Use only providers you trust with lesson excerpts, questions and your answers; starting practice and grading may incur charges.

Legacy environment configuration remains supported for advanced use: never commit `.env`. Clearing runtime configuration does not delete a legacy environment key; a restart can reload it. No environment key is bundled in this release. If no working model is configured, your answer is saved with **待评价**, never a fabricated score. Authentication, quota, connection and response-format errors produce safe messages; correct the settings and retry the same pending answer. HTML/static assets use no-store and content-versioned URLs.

### 自己上手测试评分

1. 一键启动后，打开页面顶部“模型设置”，填写供应商地址、模型名称和自己的密钥并保存。
2. 选第二节课程，读完精简知识点，点击“开始练习”，用自己的话回答并提交。
3. 配置可用时显示模型评分、分项反馈与改进表达；未成功时保留回答并显示“待评价”和安全错误提示。保存配置成功不等于供应商已验证。
4. 修改配置后，对尚未评分的原回答点击“重新评价”，无需重启。已正式评分的记录不被重复覆盖。
5. 测试结束可点“清除当前配置”；学习进度保留。关闭服务后，页面输入的密钥不保留。

## Data and privacy

The learning dashboard separates explicit read markers, evaluated practice, completed learning flows and mastery. `public_reading_bookmarks` stores per-lesson reading positions/read IDs, and `public_answer_drafts` stores unsent drafts by attempt. These are local-only SQLite tables created additively on upgrade; existing sessions, answers and scores are not replaced. Restoring a lesson/question/evaluation makes no model call. Browser close uses a best-effort checkpoint; wait for “已保存到本机” before closing when possible. A forced shutdown before saving can lose the latest unsaved changes. Historical sessions can supply prior practice location, but unrecorded historical reading positions cannot be reconstructed.

This installation assumes one trusted local learner; it has no account isolation/cloud sync, and concurrent tabs use last-write-wins checkpoints rather than conflict merging. Drafts and reading records are private data and must not be published. Restarting the local server retains database records but clears page-entered model credentials.

The first run creates `data/app.db` and seeds the public learning path. Subsequent starts synchronize owned curriculum content without deleting sessions, answers or mastery scores. Legacy extra rows are preserved but are not included in the managed public catalog. Learning records remain in that local database. Before upgrading, make a private backup; `data/backups/` is ignored by Git. Do not add course materials unless you own them or have permission to redistribute them.

## Maintaining lessons

All 60 lessons / 120 knowledge points now use the compact teaching layout established by lesson 102: three essentials (what, use, boundary), a five-step application/judgment diagram and recovery branch, one original short example, and a job-interview takeaway. Required prose is capped at 350 Chinese/ASCII characters per point (diagram labels are checked separately). Detailed principles, examples, counterexamples, application steps and interview depth are optional, collapsed by default. This cap bounds content length, not a guaranteed reading time or educational outcome.

`app/data/lesson102_teaching.json` retains the original pilot's two richer seven-section explanations. `app/data/teaching/M01.json` through `M10.json` provide individually authored meaning/action/boundary/flow/recovery/counterexample notes for the other 118 points. `app/services/compact_teaching.py` combines these with the existing original explanations, examples and product relevance without changing their text, IDs or source mapping. Each other point has five deeper sections. This is a common teaching structure, not a claim that all explanations now have identical depth or newly re-verified textbook support. New notes are original teaching organization, not source quotations. No new book access/review claims were added.

The course list includes an employment-direction selector (general AI PM or AI+education PM), stored as a browser preference. A newly started session snapshots that direction, including retests and continuation. Existing sessions retain their original direction. Lesson 102 has distinct original general/education cases with explicit scenario, constraints, decision request, interviewer rationale and task-specific scoring points. Its questions are curated rather than generated on each start; feedback and supporting services may still use the configured model. Other lessons keep their current questions and receive the role context; they do not yet all have bespoke two-track case sets.

Edit the base content in `app/data/public_curriculum.json` and compact teaching in the corresponding module note file, run `python scripts/check_curriculum.py`, and restart the app. Keep existing lesson and knowledge-point IDs when revising content. New lessons need unique IDs, module membership, objectives, at least two complete knowledge points, an original practice scenario, valid source references with section/version information, and corresponding compact notes. The loader rejects missing/extra note IDs, duplicate IDs across modules and malformed notes/flows. Keep independently authored examples distinct from source-backed explanations. Do not label a table of contents or author summary as a book chapter that was read. Changes to existing ID ownership stop synchronization rather than overwrite unrelated data. Restarting also clears page-entered runtime model credentials; re-enter them only in local model settings.

The content checker validates completeness and provenance metadata, not factual correctness or copyright clearance. Human review of the actual sources remains necessary. Reading a lesson or browsing concepts makes no model call; starting and answering practice may use the configured API.

Feedback follows the submitted question, even when the top of the page has switched to a retest: the question and saved answer are inspectable, strengths and the two most important gaps are visible, followed by a coherent optimized answer. The framework, expert answer and dimension scores are optional. Lesson 102 has 12 exact-case reference guides in `app/data/lesson102_feedback.json`; these are examples, not a unique keyword-based answer key.

If model evaluation is unavailable or falls back, the public API returns `evaluation_source=offline`, `total_score=null`, `pass_status=UNASSESSED` and `next_action=retry_evaluation`. The user's answer is saved, but no evaluation, weakness, review or mastery update is created. The same unassessed attempt may be submitted again after restoring model access. Offline reference guidance must not be presented as a personalized critique. The previous length-based fallback scoring has been removed; historical scores are not silently deleted, inflated or retrospectively regraded. A real evaluation is needed to reassess them.

## Maintaining the concept library

`app/data/concept_library.json` is the authoritative public concept content file. Each card contains a stable public ID, Chinese name, English aliases, category, definition, mechanism, usage, pitfalls, AI PM relevance, example, same-topic reading links, and reference IDs. The 150 concepts are an editorial selection for AI PM learning, not an official universal list. Explanations and examples are independently written; links point to public reference reading from Google, Hugging Face, Microsoft, Anthropic, MCP, scikit-learn, NIST, and OWASP, among others.

To revise or add cards, edit this JSON and restart the app. Startup synchronizes the owned public cards into an existing database, so existing installations receive additions without deleting course data or learning progress. Keep an existing card's ID when editing it. A new card needs a unique ID and name and valid category, related names, and source IDs. The original three public concept IDs (2001–2003) are preserved. These owned public cards are refreshed from the content file; edit that file rather than their database text. Removing a card requires an explicit content migration; synchronization does not delete stored cards.

## Checks

```powershell
python scripts/release_check.py
python scripts/audit_release.py
python scripts/check_curriculum.py
pytest -q
node --test tests/test_start_practice_ui.cjs
```

Optional browser acceptance: `python scripts/verify_compact_teaching_browser.py` (requires Playwright and Edge). This uses a temporary database and no model key; it opens all 60 lesson readers, expands/collapses all 120 points, checks four representative mobile readers and exercises offline practice/return plus concept search. It does not call a paid provider.

The release check rejects common local secrets, databases, browser state, course media, logs, and private feature routes. The privacy audit reads the actual Git index and committed blobs, checks common credential patterns, private paths, local configured secret matches and PNG metadata, and reports locations without echoing matched values. Internal `MEMORY.md` notes and local environment variants are ignored. Pattern checks do not guarantee detection of every possible secret or establish copyright clearance. See `docs/RELEASE_AUDIT.md` and review `RELEASE_CHECKLIST.md` before creating a public GitHub repository. This folder is a project copy; the original application is separate.

Python tests automatically use a temporary database/storage directory and an empty model key, never the user's learning database or API key. Browser acceptance checks use separate temporary data and an offline test model; passing them does not establish real-provider grading quality or employment outcomes.

## License

No license has been selected for this edition. Do not assume the software is available for reuse until a license is added after confirming ownership and third-party dependency terms.
