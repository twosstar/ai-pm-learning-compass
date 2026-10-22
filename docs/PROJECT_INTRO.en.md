# AI PM Learning Copilot

## Understand the knowledge. Make your next move.

A local-first learning workspace for aspiring AI product managers: follow a structured curriculum, practice decisions in product scenarios, learn from feedback, and return to where you left off.

**60 lessons · 120 stable knowledge points · 150 concept cards · Local progress · Bring your own model**

[中文介绍](PROJECT_INTRO.zh-CN.md) · [Setup and maintenance](../README.md) · [Launch copy and image guide](LAUNCH_KIT.md)

![Learning dashboard with resume action and separate progress metrics](images/learning-dashboard.png)

*Screenshots use temporary demonstration data, not a user's private learning history. Reading, assessed practice, and mastery are displayed separately.*

## Why this project exists

Learning AI product management is rarely just a matter of finding more reading material. Resources are fragmented. A definition may sound familiar without making its application clear. Practice may produce a score without a useful next step. Returning after a few days can mean searching for your place all over again.

AI PM Learning Copilot brings these activities into one workspace. It is not simply a chatbot that supplies answers or a page containing a long syllabus. Its aim is to help learners move from recognizing terminology to understanding boundaries, making a decision in a realistic situation, and explaining the trade-offs behind that decision.

The product supports career-oriented study. It does not promise employment outcomes, and a model-generated score is not a professional certification.

## Who it is for

- Beginners building a coherent foundation beyond terms such as RAG, agents, and LoRA.
- Candidates preparing to explain product decisions, technical choices, and failure handling in AI PM interviews.
- Product managers transitioning into AI and learning how data, models, evaluation, and deployment constraints connect.
- Learners and developers who want to run and edit the application locally and choose their own model provider.

The current interface and teaching content are primarily in Chinese. This English introduction does not imply a fully localized English application or curriculum.

## One connected learning journey

**Choose a lesson → Study the concept → Examine its boundaries → Answer a question → Review feedback → Save progress → Continue.**

### A structured path, not a pile of terms

The public curriculum contains 10 modules, 60 lessons, and 120 stable knowledge points:

| Module | Focus |
|---|---|
| Product problems and orientation | User needs, competition, requirements, constraints, and acceptance criteria |
| Machine learning and evaluation | Task types, classification and regression, error trade-offs, generalization, and model selection |
| Data and experiments | Splits, leakage, annotation, drift, and reproducibility |
| Language models and Transformers | Tokens, embeddings, pretraining, attention, architecture, and sampling |
| Prompts, context, and adaptation | Instructions, structured outputs, fine-tuning, LoRA, and preference training |
| Retrieval and RAG | Ingestion, chunking, lexical and dense retrieval, reranking, citations, and evaluation |
| Agents, tools, and control | Workflows, tool contracts, state, memory, permissions, and recovery |
| Vision, speech, and related tasks | Visual tasks, transcription, multimodality, recommendations, and extraction |
| Inference and deployment | Latency, throughput, caching, quantization, distillation, resources, releases, and costs |
| Experience, safety, and applied design | Onboarding, explanations, feedback, data boundaries, human control, and launch decisions |

Search and module navigation help learners find a topic. Stable lesson and knowledge-point IDs allow teaching content to evolve without replacing the identity of saved learning records.

### Concise by default, deeper when needed

Every knowledge point follows the same instructional structure:

- **What it is:** a plain-language explanation.
- **How to use it:** an actionable connection to product work.
- **Where it stops:** limitations and inappropriate uses.
- **A decision or application diagram:** key steps and a recovery branch.
- **A short original example and interview takeaway.**
- **Optional depth:** principles, counterexamples, application steps, and fuller explanations behind a disclosure.

Required prose has a length limit; detailed explanations are not all expanded at once. Diagrams are authored for each topic and describe an application or decision path, rather than claiming every concept is the same technical pipeline.

![Lesson reader with concise explanations, a responsibility diagram, and optional detail](images/lesson-reader.png)

### Practice product judgment, not definition recall alone

Questions encourage learners to explain goals, constraints, choices, trade-offs, and recovery. For example: which decisions belong to a model and which belong to application logic? Why is blindly retrying a timed-out action unsafe? Why can an answer with a citation still be wrong?

The application supports general AI PM and AI-in-education PM study directions. Lesson 102 currently has bespoke cases for both directions and multiple practice stages. Other lessons retain their existing generated or fallback question mechanisms; they do not yet all have equally developed two-track case collections.

### Feedback without invented offline scores

With a working compatible model configured, learners can submit answers and inspect strengths, priority gaps, improved wording, and dimension-level feedback. Current dimensions cover conceptual accuracy, technical understanding, product thinking, application scenarios, and communication structure.

If no model is configured, authentication fails, usage is limited, or the response format is incompatible, the application saves the answer and shows an unassessed state. It does not invent a score from answer length or present a fallback reference as a personalized assessment.

A previously unassessed answer can be retried after correcting the configuration. Restoring an already evaluated answer displays its saved evaluation instead of issuing another grading request.

![Offline practice state: answer retained without a fabricated score](images/practice-offline.png)

*This image demonstrates the unconfigured/offline state, not a real model assessment. Scores are practice feedback, not evidence of interview success or professional accreditation.*

### Resume instead of starting over

The dashboard displays the last lesson and knowledge point with a clear resume action. Course rows distinguish not started, reading, practicing, and completed learning flows, alongside separate reading, assessed-practice, and mastery metrics.

Reading positions, explicit read markers, practice sessions, and drafts are stored in the local database. Reloading or reopening the browser can recover the original question and answer rather than generating a replacement just to resume.

A read marker is a learner-controlled bookmark, not a mastery award. Completing a learning flow does not certify every skill. Positions that were never recorded by an earlier version cannot be reconstructed retrospectively.

### A searchable library of 150 concept cards

The concept map contains 150 independently authored cards across 10 topics, with Chinese/English names and abbreviations, topic filters, pagination, examples, boundaries, and related-concept navigation. It is a searchable card library, not an interactive node-and-edge graph.

The selection is editorial, not an officially mandated universal list. Reading lessons and browsing cards do not require model API calls.

![Concept search, topic navigation, and cards](images/concept-map.png)

## Run locally and bring your own model

1. Install Python 3.11 or newer.
2. On Windows, double-click `Start Learning Copilot.bat` in the project root. The first run creates an environment and installs dependencies, requiring internet access and some waiting time.
3. Keep the launch window open and visit `http://127.0.0.1:8001/`.
4. Read lessons, browse concepts, and save positions or drafts without a configured model. For model-based evaluation, open **模型设置** at the top of the page.
5. Enter a trusted provider's HTTPS OpenAI-compatible chat API base URL, exact model identifier, and your own key; acknowledge the data-sharing and cost notice before saving.

Saving configuration makes no provider request and does not verify connectivity. Starting practice and requesting evaluations may contact the selected provider and incur charges. Compatibility depends on the provider, model, and structured response behavior; not every advertised compatible endpoint is guaranteed to work.

## Data and content boundaries

- Page-entered keys are held only in the current local server process. The application does not write them to project files, the learning database, or browser persistent storage. Re-enter them after restarting the server. Requests already in flight may complete after configuration is cleared.
- Learning records and drafts live in the local database and are not release assets. Reloading does not delete them, but deleting the data directory, moving to a new installation, or changing computers does not automatically migrate them.
- Once enabled, the chosen provider may receive relevant teaching excerpts, questions, and answers. Local persistence does not mean inference is fully offline.
- This is a trusted, local, single-learner application, not a multi-tenant SaaS with account isolation, cloud sync, or public credential hosting. Do not expose the local server directly to the internet.
- The public edition uses an independently arranged syllabus and original teaching organization with retained public-reference metadata. It does not bundle purchased course videos, slides, handouts, transcripts, commercial question banks, or full books.
- Reference links are for reading and maintenance, not proof of permission to redistribute source text. Automated checks do not replace human factual review, rights review, or professional judgment.

## For maintainers and developers

The front end uses HTML, CSS, and JavaScript. FastAPI serves the local application, while SQLAlchemy persists learning records in SQLite. Curriculum, concept, and teaching overlays are editable JSON assets; lesson reading does not generate its main content online.

- `app/data/public_curriculum.json`: base curriculum, explanations, and provenance.
- `app/data/teaching/M01.json` through `M10.json`: point-specific concise explanations, boundaries, paths, and counterexamples.
- `app/data/lesson102_teaching.json`: the richer lesson 102 teaching overlay.
- `app/data/concept_library.json`: concept cards.
- `tests/` and `scripts/`: curriculum, release, and behavior checks.

Keep existing IDs when editing, run checks before restarting, and keep databases, backups, environment files, and logs private. Software reuse is governed by the eventual project license and applicable dependency terms. A project license has not yet been selected in this repository.

## Current scope and next steps

The current public surface focuses on smart learning and concept exploration. Private course collection, browser control, and paid-material import workflows are not exposed. A packaged desktop installer, full English localization, multiple user accounts, and cloud cross-device sync have not been delivered and should not be advertised as available features.

Feedback is especially useful on factual accuracy, readability, case quality, recovery behavior, and provider compatibility. The goal remains practical understanding and useful improvement, rather than increasing terminology counts alone.

![Responsive mobile learning dashboard](images/mobile-dashboard.png)

*This is a responsive web view, not a released native mobile application.*
