# AI PM Learning Copilot — Public Edition

**English project guide · Chinese-first learning experience · Local-first**

[中文 README](README.md) · [English project introduction](docs/PROJECT_INTRO.en.md) · [中文项目介绍](docs/PROJECT_INTRO.zh-CN.md) · [Launch kit](docs/LAUNCH_KIT.md)

![Local learning workspace with resumable progress](docs/images/learning-dashboard.png)

Screenshots use temporary demo records, not private learning data. The interface and lessons are primarily in Chinese; bilingual project introductions are available.

An independent, local-first learning companion for AI product-management concepts. The first public release focuses on smart learning, a concept map, answer feedback, and locally persisted progress through a public sample path.

## Scope and curriculum

The sample lessons and concept cards were independently written for this public edition as general educational material, not as reproductions of a paid course. The project excludes course videos, slides, handouts, transcripts, proprietary question banks, collected course materials, browser profiles, databases, and private-app learning records.

The authoritative curriculum is `app/data/public_curriculum.json`: 60 lessons in 10 independently arranged modules, with 120 fixed knowledge points. It preserves the first three public lesson IDs (101–103) and six original public knowledge-point IDs (1001–1006). `sample_curriculum.json` is retained only as a historical sample and ID reference. No private course outline or database is imported.

46 lessons cite publicly readable textbook chapters; the other 14 refer to guides, official documentation, research papers, or author chapter summaries. Lessons include objectives, explanations, original business examples, and original practice tasks before questions. Detailed source panels are not shown in the reader; provenance remains in the curriculum JSON and API for maintenance. Links are references only: they are not redistributed books and do not imply permission to copy their prose. See [CURRICULUM_SOURCES.md](CURRICULUM_SOURCES.md) for scope and limitations.

## Features

- Smart learning along the included public path.
- Generated or fallback questions, answer evaluation, feedback, and remediation.
- Local SQLite persistence for attempts, mastery, and progress.
- A concept map with 150 independently authored cards, 10 topic filters, Chinese/English search, examples, related reading, and references. Browsing does not call a model API.
- A continue action that advances to the next eligible knowledge point.

The public HTTP surface exposes only health, catalog, concept-map reads, and the learning start/answer/continue flow. Course collection, browser control, file import, interview practice, question-bank import, and V2 training are not mounted.

## Install and launch

Requires Python 3.11 or later. On Windows, double-click `Start Learning Copilot.bat`. On first run, it creates a local virtual environment and installs dependencies; this may take a few minutes and requires internet access. It creates `.env` from `.env.example` only if `.env` does not already exist, then starts the app and opens <http://127.0.0.1:8001/>. Keep the console window open while using the app. Press `Ctrl+C` in that window to stop it.

## Configure answer evaluation

1. Open **模型设置** (Model Settings) at the top of the page.
2. Enter a trusted provider's HTTPS OpenAI-compatible API base URL, exact model name, and your own API key.
3. Review and acknowledge provider access and cost, then save.
4. Start a practice or retry a pending evaluation to make the first real provider request.

Saving settings makes no provider request and requires no restart. Never send keys in chat. If port 8001 is occupied, close the other app and launch again.

This public edition does not inherit the original application's model key. A key entered on the page stays only in the local server process: it is not written to files, the learning database, `localStorage`, or `sessionStorage`, and is never returned by the settings API. Password fields clear on save/close; restarting the server requires re-entry. Clearing settings disables future calls, though an in-flight request may still finish. The settings API accepts loopback/same-origin access only and requires a process token for changes. Provider URLs must use HTTPS and must not embed credentials or query parameters.

This build is for trusted local use—not public multi-user hosting or an untrusted-device security boundary. Use only providers you trust with lesson excerpts, questions, and answers. Starting practice and grading may send that content to the provider and can incur charges.

Legacy environment configuration remains available for advanced use; never commit `.env`. Clearing runtime settings does not remove a legacy environment key, which could reload on restart. No key is bundled with this release. If no working model is configured, answers are saved as **待评价** (Pending evaluation), never assigned fabricated scores. Authentication, quota, connection, and response-format errors produce safe messages; fix the settings and retry the same pending answer. HTML and static assets use no-store behavior and versioned asset URLs.

### Test scoring yourself

1. Launch the app, open **模型设置**, enter your provider URL, model name, and key, then save.
2. Choose a lesson, read its knowledge points, select **开始练习** (Start practice), answer in your own words, and submit.
3. When the provider works, the app shows a model score, dimension feedback, and an improved expression. On failure, the answer remains saved as **待评价**. Saving settings alone does not verify provider connectivity.
4. After fixing settings, select **重新评价** (Retry evaluation) for a pending answer; no restart is needed. Completed evaluations are not overwritten.
5. Clear the current settings after testing if desired. Learning progress remains. Page-entered keys are cleared when the server stops.

## Data and privacy

The dashboard distinguishes explicit reading markers, evaluated practice, completed learning flows, and mastery. `public_reading_bookmarks` stores per-lesson reading positions and read IDs; `public_answer_drafts` stores unsent drafts by attempt. These local SQLite tables are created additively and do not replace existing sessions, answers, or scores. Restoring a lesson, question, or evaluation makes no model call. Browser close uses a best-effort checkpoint; wait for **已保存到本机** (Saved locally) when possible. A forced shutdown before saving may lose the latest changes. Historical sessions can help recover practice location, but unrecorded historical reading positions cannot be reconstructed.

This installation assumes one trusted local learner. It has no account isolation or cloud sync. Concurrent tabs use last-write-wins checkpoints without conflict merging. Drafts and reading records are private and must not be published. Restarting the local server retains the learning database but clears page-entered model credentials.

The first run creates `data/app.db` and seeds the public path. Later starts synchronize owned curriculum content without deleting sessions, answers, or mastery. Legacy extra rows are preserved but excluded from the managed public catalog. Learning records remain in the local database. Make a private backup before upgrading; Git ignores `data/backups/`. Add course materials only if you own them or have permission to redistribute them.

## Maintaining lessons

All 60 lessons and 120 knowledge points use a compact teaching layout based on lesson 102: three essentials (what, use, boundary), a five-step application/judgment diagram with a recovery branch, one original short example, and a job-interview takeaway. Required prose is capped at 350 Chinese/ASCII characters per point (diagram labels are checked separately). Deeper principles, examples, counterexamples, application steps, and interview detail are optional and collapsed by default. The cap controls length; it does not guarantee reading time or learning outcomes.

`app/data/lesson102_teaching.json` retains the pilot's two richer seven-section explanations. `app/data/teaching/M01.json` through `M10.json` provide independently authored meaning/action/boundary/flow/recovery/counterexample notes for the other 118 points. `app/services/compact_teaching.py` combines these with existing explanations, examples, and product relevance without changing their text, IDs, or source mapping. This shared structure does not claim identical depth or newly verified textbook support. Added notes are original teaching organization, not quotations; no new book-access or review claims were added.

The course list offers a job-direction preference (general AI PM or AI+education PM), stored in the browser. New sessions snapshot the selected direction; existing sessions retain theirs. Lesson 102 has distinct original general and education cases with explicit scenarios, constraints, decision requests, interviewer rationale, and task-specific scoring points. These questions are curated, not regenerated on every start; feedback and supporting services may still use the configured model. Other lessons receive role context but do not yet all have bespoke two-track case sets.

Edit `app/data/public_curriculum.json` and the corresponding module teaching-note file, run `python scripts/check_curriculum.py`, and restart the app. Preserve existing lesson and knowledge-point IDs. New lessons require unique IDs, module membership, objectives, at least two complete knowledge points, an original practice scenario, valid source references with section/version information, and corresponding compact notes. The loader rejects missing/extra note IDs, duplicate IDs across modules, and malformed notes/flows. Keep original examples distinct from source-backed explanations. Do not label a table of contents or author summary as a book chapter that was read. Changing existing ID ownership stops synchronization rather than overwriting unrelated data. Restarting also clears page-entered runtime model credentials; re-enter them only in local model settings.

The content checker validates completeness and provenance metadata, not factual correctness or copyright clearance. Human review of the actual sources remains necessary. Reading lessons or browsing concepts makes no model call; starting and answering practice may use the configured API.

Feedback follows the submitted question even if the page has switched to a retest: the question and saved answer remain inspectable. Strengths, the two most important gaps, and a coherent improved answer are shown first; answer frameworks, expert answers, and dimension scores are optional. Lesson 102 has 12 exact-case reference guides in `app/data/lesson102_feedback.json`; these are examples, not a unique keyword-based answer key.

If model evaluation is unavailable or falls back offline, the public API returns `evaluation_source=offline`, `total_score=null`, `pass_status=UNASSESSED`, and `next_action=retry_evaluation`. The answer is saved, but no evaluation, weakness, review, or mastery update is created. Retry the same unassessed attempt after restoring model access. Offline reference guidance must not be presented as personalized critique. Length-based fallback scoring has been removed; historical scores are not silently deleted, inflated, or retrospectively regraded. A real evaluation is required to reassess them.

## Maintaining the concept library

`app/data/concept_library.json` is the authoritative public concept file. Each card includes a stable public ID, Chinese name, English aliases, category, definition, mechanism, usage, pitfalls, AI PM relevance, example, related reading, and reference IDs. The 150 concepts are an editorial selection for AI PM learning, not an official universal list. Explanations and examples are independently written; links point to public references from Google, Hugging Face, Microsoft, Anthropic, MCP, scikit-learn, NIST, OWASP, and others.

Edit this JSON to revise or add cards, then restart the app. Startup synchronizes the owned public cards into an existing database without deleting course data or progress. Keep an existing card's ID when editing. A new card needs a unique ID and name, valid category, related names, and source IDs. The original three public concept IDs (2001–2003) are preserved. These cards are refreshed from the content file, so edit the JSON rather than database text. Removing a card requires an explicit data migration; synchronization does not delete stored cards.

## Checks and release

Run in Windows PowerShell:

```powershell
python scripts/release_check.py
python scripts/audit_release.py
python scripts/check_curriculum.py
pytest -q
node --test tests/test_start_practice_ui.cjs
```

Optional browser acceptance: `python scripts/verify_compact_teaching_browser.py` (requires Playwright and Edge). It uses a temporary database and offline test model with no API key; opens all 60 lesson readers, expands/collapses all 120 points, checks four representative mobile readers, and exercises offline practice/return and concept search. It does not call a paid provider.

The release check rejects common local secrets, databases, browser state, course media, logs, and private feature routes. The privacy audit reads the Git index and committed blobs, checks common credential patterns, private paths, matches against locally configured secrets, and PNG metadata; it reports locations without echoing matched values. Internal `MEMORY.md` notes and local environment variants are ignored. Pattern checks cannot guarantee that every secret is detected or establish copyright clearance. Review [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) and [docs/RELEASE_AUDIT.md](docs/RELEASE_AUDIT.md) before creating a public GitHub repository. This folder is a separate project copy; the original application is separate.

Python tests use a temporary database/storage directory and empty model key, never the real learning database or API key. Browser acceptance uses separate temporary data and an offline test model. Passing tests does not establish real-provider grading quality or employment outcomes.

## License

No software license has been selected for this edition. Do not assume the project is available for reuse until ownership and third-party dependency terms have been confirmed and a license is added.
