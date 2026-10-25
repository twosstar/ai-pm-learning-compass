# AI PM Learning Compass

**A Chinese-first, local-first study companion for AI product management and job interview practice.**

[中文 README](README.md) · [English project introduction](docs/PROJECT_INTRO.en.md) · [中文项目介绍](docs/PROJECT_INTRO.zh-CN.md) · [Launch kit](docs/LAUNCH_KIT.md)

Learn AI product concepts through real product situations: understand the idea, practice making a decision, then review what was strong and what your answer still needs.

## Product tour

These images use temporary demo records. The score screen uses a mock evaluation; no private learning records, real answers, or API keys are included.

| Learning home | Scenario practice |
|---|---|
| <img src="docs/images/learning-dashboard.png" alt="Learning home with curriculum and local progress" width="100%"> | <img src="docs/images/practice-question.png" alt="AI PM interview scenario and answer field" width="100%"> |
| **Score and answer feedback** | **Concept map** |
| <img src="docs/images/score-feedback.png" alt="Mock score, strengths, gaps, and a sample improved answer" width="100%"> | <img src="docs/images/concept-map.png" alt="Searchable AI product concept cards organized by topic" width="100%"> |

## What you can do

- **Follow a structured learning path:** 60 lessons across 10 modules, covering 120 knowledge points. Reading and practice progress stays on your device so you can pick up where you left off.
- **Practice job-relevant product decisions:** Work through original AI product scenarios, with a general AI PM or AI+education direction.
- **Get useful answer feedback:** Review strong points, important gaps, dimension scores, and a sample improved answer. If the model provider is unavailable, an answer stays **Pending evaluation**; the app does not invent a score.
- **Explore the concept map:** Browse 150 topic-organized cards with Chinese and English search. Browsing concepts does not call a model API.

This is an independently authored public learning project, not a reproduction of a paid course. It does not include course videos, handouts, transcripts, proprietary question banks, private databases, or learning records from the original application. See [curriculum source notes](CURRICULUM_SOURCES.md) for scope and limitations.

## Run on Windows

### Desktop installer

When a formal release is published, download the latest `AI-PM-Learning-Compass-Setup-X.Y.Z.exe` from [GitHub Releases](https://github.com/twosstar/ai-pm-learning-compass/releases) and follow the installer. Python and administrator access are not required. Microsoft Edge WebView2 Runtime is required; if it is missing, follow the installer's link to Microsoft's download page and run the installer again. Beta builds are currently unsigned, so Windows may show an unknown-publisher warning.

A fresh install starts with empty learning records; no developer progress or API key is included. Learning data lives at `%LOCALAPPDATA%\AI PM Learning Compass\data`, and non-secret model preferences live under `%LOCALAPPDATA%\AI PM Learning Compass\config`. The API key stays in memory by default. If **Remember this device** is selected, it is stored in the current Windows user's Credential Manager. Updating or uninstalling the app leaves local learning data and saved preferences in place.

The app checks for a formal release on startup and every six hours while open. After downloading and verifying an installer, it asks whether to install and restart. Installation is visible and can be postponed. The app does not check in the background while closed or force an update.

### Run from source

Requires **Python 3.11 or later**.

1. Download or clone this repository.
2. Double-click `Start Learning Copilot.bat`. On first launch, it creates a local environment and installs dependencies; allow a few minutes and an internet connection.
3. The app opens in your browser. Keep the console window open while using it; press `Ctrl+C` there to stop the service.

By default, the app runs at [http://127.0.0.1:8001/](http://127.0.0.1:8001/). Reading lessons and browsing concepts do not require model configuration.

### Enable AI scoring

Open **模型设置** (Model Settings) at the top of the page. Enter a trusted provider's HTTPS OpenAI-compatible API URL, exact model name, and your own API key. Review the data-transfer and cost notice before saving. Saving makes no provider request; the first practice or retry of a pending evaluation makes the call.

By default, the key entered on the page is held only in the local server process. The desktop edition can optionally save it to the current Windows user's Credential Manager; it is never written to the ordinary preferences file, learning database, or browser storage. Practice and scoring may send lesson excerpts, questions, and answers to your chosen provider and may incur charges. Never share a key in chat or commit one to the repository. This edition is for trusted local use, not direct public multi-user hosting.

## Local data and public content

Progress, drafts, and answer attempts are stored in a local SQLite database by default. There are no user accounts or cloud sync. The curriculum source is `app/data/public_curriculum.json`; the authoritative content for the 150 concept cards is `app/data/concept_library.json`. Curriculum checks validate structure and source metadata, but do not replace human fact-checking or establish copyright permission.

For technical details, see [curriculum source notes](CURRICULUM_SOURCES.md), the [release checklist](RELEASE_CHECKLIST.md), [privacy and release audit](docs/RELEASE_AUDIT.md), and the [launch kit](docs/LAUNCH_KIT.md). No software license has been selected; do not assume reuse is permitted until ownership and dependency terms are confirmed.
