# Windows Desktop Installer and Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking. Do not delegate work in this session.

**Goal:** Deliver a Windows per-user installer for AI PM Learning Compass, with private local learner data, optional Windows Credential Manager key storage, and app updates published only from formal version tags.

**Architecture:** A pywebview desktop host starts the existing FastAPI app on loopback and points its writable paths into `%LOCALAPPDATA%`. PyInstaller and Inno Setup create a per-user installer. The app checks public GitHub Releases, downloads and verifies a newer installer, then requests confirmation before launching the visible installer and restarting. GitHub Actions runs only for `vMAJOR.MINOR.PATCH` tags and publishes only after packaging and payload privacy checks succeed.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, pywebview/WebView2, SQLAlchemy/SQLite, keyring Windows Credential Manager backend, PyInstaller, Inno Setup, GitHub Actions, `uv` lockfile.

**Spec:** `docs/superpowers/specs/2026-10-24-windows-desktop-distribution-design.md`

## Global Constraints

- Windows desktop app in an independent window, using pywebview to host the existing local FastAPI application and static UI.
- On formal version tags only, GitHub Actions builds and publishes; ordinary pushes to `main` do not publish an installer.
- The app checks GitHub Releases on launch and periodically while open; after download it verifies SHA-256 and asks before installing/restarting.
- Every new installation starts with an empty learning database; upgrades preserve each learner's own local database.
- The learner supplies and pays for their own model API; requests go directly to their selected HTTPS provider.
- API key persistence is optional; when selected, use Windows Credential Manager. Never return the key through a settings API or package it.
- The installer excludes `.env`, keys, SQLite databases, progress records, browser profiles, and local caches.
- First beta installer is unsigned; Chinese-first install and update messages disclose the Windows publisher warning.
- Do not add or run automated tests in this implementation. Use only the specified manual smoke checks and package privacy audit.

---

## File Map

- `app/desktop/launcher.py` — configure per-user paths before app import, reserve a loopback socket, run Uvicorn, open and close the desktop window.
- `app/desktop/update_helper.py` — wait for app shutdown, launch a visible installer, and relaunch only after successful install.
- `app/core/config.py` and `app/db/session.py` — prevent packaged mode from reading a working-directory `.env`; resolve all mutable data into the per-user directory.
- `app/services/model_credentials.py` — read/write/delete saved API keys through an explicitly selected Windows Credential Manager backend; store only non-secret provider preferences in the per-user config directory.
- `app/api/routes/public_model_settings.py` — expose key-present/remembered status without ever returning the key; preserve the current loopback, same-origin, process-token safeguards.
- `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css` — add the “remember this device” option and update prompt/status UI.
- `app/services/desktop_updates.py` — check release metadata, compare versions, download only the expected installer asset, and verify its checksum.
- `app/api/routes/desktop_updates.py` and `app/main.py` — expose desktop-only local update status/download/accept actions.
- `app/version.py` — package version interface populated by the release build.
- `packaging/windows/ai_pm_learning.spec` — PyInstaller inputs, hidden imports, public curriculum/static resources, version data, and executable outputs; Task 4 adds the updater helper output.
- `packaging/windows/installer.iss` — per-user Inno Setup install/upgrade/uninstall behavior and WebView2 prerequisite handling; Task 4 adds update-invocation behavior.
- `packaging/windows/app.ico` — app icon derived from the existing cloud companion brand artwork.
- `scripts/build_windows.py` — create version metadata, invoke PyInstaller and Inno Setup, and produce a clean staging directory.
- `scripts/audit_installer_payload.py` — inspect the actual staged payload for forbidden private files and credential patterns without reading `.env`.
- `.github/workflows/release-windows.yml` — validate the pushed version tag, build/audit, and publish the GitHub Release with installer and SHA-256 metadata.
- `pyproject.toml` and `uv.lock` — declare desktop/keyring dependencies and pin the dependency graph used in CI.
- `README.md`, `README.en.md`, and `RELEASE_CHECKLIST.md` — explain install, user-paid model API, local data, formal tag release steps, update behavior, and unsigned beta warning.

## Task 1: Isolate Desktop Runtime and Per-User Data

**Files:**
- Create: `app/desktop/__init__.py`
- Create: `app/desktop/launcher.py`
- Create: `app/version.py`
- Modify: `app/core/config.py`
- Modify: `app/db/session.py`
- Modify: `app/main.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `app.desktop.launcher.main() -> int`, `app.version.get_version() -> str`, and a launcher runtime setup that writes `STORAGE_DIR`, `DATABASE_URL`, `CHROMA_PATH`, `APP_HOST`, and `APP_PORT` into the environment before importing `app.main`.
- Consumes: existing `app.main:app`, `api/health`, `Settings`, `engine`, and current public-curriculum startup seeding.

- [ ] **Step 1: Add desktop dependencies and lockfile**

Add `pywebview` and `keyring` to `pyproject.toml`, install/pin `uv` in the build workflow later, and generate `uv.lock` from the declared project dependencies. Keep current browser launch dependencies available for developer use.

- [ ] **Step 2: Add packaged version lookup**

Implement `get_version()` to read a build-generated version resource in frozen mode and fall back to the project version for local source runs. Fail closed on malformed version strings rather than treating them as a newer release.

- [ ] **Step 3: Add per-user runtime path setup**

In `launcher.py`, resolve `%LOCALAPPDATA%\AI PM Learning Compass`; create `data` and `config` subdirectories; set absolute `DATABASE_URL` and `CHROMA_PATH`; set loopback-only host; and reserve a free loopback socket so Uvicorn can serve through the already-bound socket without exposing a LAN interface.

- [ ] **Step 4: Keep `.env` loading for source mode only**

Update settings construction so a frozen desktop process uses environment configuration only and never auto-loads `.env` from the install/current directory. Leave the current source-mode `.env` workflow intact.

- [ ] **Step 5: Host the app in a standalone window**

Build a Uvicorn `Server` for the existing FastAPI object after runtime paths are set. Start it on a daemon thread, wait up to 60 seconds for `/api/health`, then open one pywebview window at the local URL with a desktop marker query. On window close set `server.should_exit`, close the reserved socket, and wait for shutdown. Show a Chinese actionable error if WebView2 is unavailable.

- [ ] **Step 6: Manually verify clean and persistent paths**

Run the desktop launcher from a disposable Windows profile. Confirm that public course data initializes, learner history is created only below `%LOCALAPPDATA%\AI PM Learning Compass\data`, no data appears under the installation directory, and closing the window exits the server. Do not inspect or copy the developer `.env` or local database.

## Task 2: Add Optional Credential Manager Storage

**Files:**
- Create: `app/services/model_credentials.py`
- Modify: `app/api/routes/public_model_settings.py`
- Modify: `app/services/llm.py`
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`

**Interfaces:**
- Produces: `save_model_preferences(base_url: str, model: str) -> None`, `load_model_preferences() -> dict[str, str]`, `save_api_key(api_key: str) -> None`, `load_api_key() -> str | None`, and `clear_model_credentials() -> None`.
- Consumes: existing `LLMService.configure_runtime(api_key, base_url, model)`, `clear_runtime()`, and loopback-only settings routes.

- [ ] **Step 1: Add a per-user non-secret config file**

Store provider URL and model only under `%LOCALAPPDATA%\AI PM Learning Compass\config\model.json`. Write atomically using a temporary sibling file and replace; reject unexpected keys and never serialize API-key values.

- [ ] **Step 2: Pin the Windows Credential Manager backend**

Use the `keyring` library's Windows Credential Manager backend explicitly on Windows. Do not accept an arbitrary plaintext fallback backend. If Credential Manager is unavailable, report a safe local message and keep the current key in process memory only.

- [ ] **Step 3: Persist only when the learner opts in**

Extend `PUT /api/model-settings` with `remember_api_key: bool`. Always apply the submitted key to the in-memory LLM service. Save it to Credential Manager only when checked; if unchecked, remove any previously saved key. Store URL/model preferences without the key. On service startup restore URL/model and restore the key only when the vault entry exists.

- [ ] **Step 4: Keep the API response secret-free**

Return booleans such as `configured` and `remembered` plus safe model/provider fields. Never echo the secret, even on validation or vault errors. Ensure `DELETE /api/model-settings` clears process memory, the vault entry, and saved URL/model preferences.

- [ ] **Step 5: Add the user-facing checkbox and copy**

Add “记住此设备” with a short explanation that the key is stored by Windows and remains on this device. Keep unchecked by default. Update save/clear status so it accurately distinguishes session-only and remembered settings; continue clearing the password input when the dialog closes.

- [ ] **Step 6: Manually verify key lifecycle**

In a disposable Windows profile, save once with the checkbox off and once on; restart the app and confirm the first key is absent while the second is configured but never displayed. Clear settings and confirm subsequent startup no longer configures a model. Do not use or display any real provider key during this check.

## Task 3: Build a Per-User Windows Installer

**Files:**
- Create: `packaging/windows/ai_pm_learning.spec`
- Create: `packaging/windows/installer.iss`
- Create: `packaging/windows/app.ico`
- Create: `scripts/build_windows.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `scripts/build_windows.py --version X.Y.Z --output <directory>`, resulting in a staging directory containing the desktop executable, required public app resources, installer executable, and SHA-256 manifest. Task 4 adds the updater helper executable.
- Consumes: Task 1 launcher/version interfaces, project dependency lock, `app/data/public_curriculum.json`, `app/data/concept_library.json`, and `app/static` assets.

- [ ] **Step 1: Add a Windows PyInstaller spec**

Package only runtime code, required dependencies, public curriculum/concept JSON, and static UI assets. Exclude `.env*` except no environment example is needed at runtime; exclude `.git`, `data`, `.venv`, logs, tests, browser profiles, and developer caches. Output one desktop executable; Task 4 adds a separate updater helper executable after implementing its behavior.

- [ ] **Step 2: Add a package payload privacy audit**

Implement `scripts/audit_installer_payload.py <staging-directory>`. Fail if the payload contains `.env`, database/SQLite files, `data/chroma`, logs, browser profiles, user-specific absolute paths, or credential-format strings. The audit must read only the staged package and must not inspect local environment variables, `.env`, or user data.

- [ ] **Step 3: Build versioned application files**

Have `build_windows.py` validate `X.Y.Z`, write a temporary packaged version resource, run PyInstaller with the spec, remove the temporary generated source, and ensure the staging tree starts empty before every build.

- [ ] **Step 4: Add per-user Inno Setup behavior**

Install below `%LOCALAPPDATA%\Programs\AI PM Learning Compass` with no administrator requirement. Replace application files in place on update; never add uninstall deletion rules for `%LOCALAPPDATA%\AI PM Learning Compass`. Check for WebView2 runtime; if missing, launch Microsoft's Evergreen bootstrapper and show a clear internet requirement. Add Start Menu/Desktop shortcuts and visible uninstall support.

- [ ] **Step 5: Produce and audit the installer**

Compile with `ISCC.exe`, place the installer and checksum manifest in the output directory, then run the payload privacy audit against the exact staged files that Inno Setup will package. Also verify that the installer output contains only the expected installer and checksum manifest. Fail the build if any forbidden staged artifact is found.

- [ ] **Step 6: Manually verify install and upgrade persistence**

Install into a clean disposable Windows profile and confirm no Python installation is required. Create disposable progress and a synthetic remembered credential, install a later version over it, and confirm both remain. Uninstall and verify data remains unless the learner explicitly removed it in-app.

## Task 4: Add Safe Release Checking and Update UX

**Files:**
- Create: `app/services/desktop_updates.py`
- Create: `app/api/routes/desktop_updates.py`
- Create: `app/desktop/update_helper.py`
- Modify: `app/main.py`
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Modify: `packaging/windows/ai_pm_learning.spec`

**Interfaces:**
- Produces: `check_for_update(current_version: str) -> dict`, `download_update(version: str) -> dict`, and `launch_verified_installer() -> None` using only the installer path retained by the update service after checksum verification.
- Consumes: `get_version()`, public GitHub Releases API for `twosstar/ai-pm-learning-compass`, the release asset `AI-PM-Learning-Compass-Setup-X.Y.Z.exe`, `SHA256SUMS.txt`, and the packaged `update-helper.exe`.

- [ ] **Step 1: Validate release metadata**

Read only HTTPS GitHub release metadata. Accept only a non-draft, non-prerelease release whose tag matches `vX.Y.Z`, whose installer asset name matches the tag version, and whose checksum manifest contains exactly one matching installer entry. Reject malformed, lower/equal, or unsupported versions.

- [ ] **Step 2: Download and verify the installer**

Download into a per-user temporary update folder using a `.part` file. Enforce HTTPS, maximum installer size, and a fixed GitHub release asset host; stream SHA-256 during download; compare it with the release manifest; atomically rename only after a match. Delete partial files on all errors. A failed network check must not block learning.

- [ ] **Step 3: Expose update status locally**

Mount update routes only for the desktop window marker. Preserve loopback, same-origin, no-store protections. Return release version, download state, and safe error codes only; never accept an arbitrary installer path or URL from the browser. Expose `GET /api/desktop-update/check` and `POST /api/desktop-update/install`.

- [ ] **Step 4: Add launch and periodic checks**

From desktop UI initialization, check once on launch and then every six hours while open. If a newer installer is verified, show a Chinese prompt with version and “稍后 / 安装并重启”. Do not show a blocking prompt for offline/network errors and do not check in normal browser mode.

- [ ] **Step 5: Implement confirmed visible installation**

After `POST /api/desktop-update/install` is called in response to “安装并重启”, start the packaged helper with the verified installer path and current process ID, then close the desktop window normally. The helper waits for app exit, launches the Inno Setup installer visibly, waits for completion, and relaunches the installed app only when the installer exits successfully. Do not pass quiet-install switches or terminate the app before user confirmation.

- [ ] **Step 6: Manually verify updater failure paths**

Using a local test release fixture or a draft-free disposable release asset, check current-version/no-update, newer-version prompt, corrupt checksum rejection, interrupted download cleanup, offline startup, learner choosing “稍后”, and successful visible update/relaunch. Confirm learning data is untouched in every failure path.

## Task 5: Automate Formal GitHub Releases

**Files:**
- Create: `.github/workflows/release-windows.yml`
- Create: `uv.lock`
- Modify: `scripts/build_windows.py`
- Modify: `scripts/audit_installer_payload.py`
- Modify: `RELEASE_CHECKLIST.md`

**Interfaces:**
- Trigger: pushed tag matching `v*.*.*`; no `push` to `main` trigger and no periodic scan.
- Produces: public GitHub Release containing `AI-PM-Learning-Compass-Setup-X.Y.Z.exe` and `SHA256SUMS.txt` only after build and audit succeed.

- [ ] **Step 1: Define tag-only workflow permissions and trigger**

Use `on.push.tags: ["v*.*.*"]`, `permissions.contents: write`, a Windows runner, and fetch full history. Do not add secrets, PATs, deploy keys, or API keys. Do not trigger a release from ordinary main commits.

- [ ] **Step 2: Validate the tag before building**

Require exact semantic version `vMAJOR.MINOR.PATCH`, require the tagged commit to be reachable from `main`, and reject a tag that is not greater than the newest published stable semantic version.

- [ ] **Step 3: Build from a clean locked checkout**

Set up Python 3.11 and a pinned `uv` version; run `uv sync --frozen`; invoke `scripts/build_windows.py` with the tag version; fail if the stage directory is not clean or the payload audit returns any finding.

- [ ] **Step 4: Publish only after all prior steps pass**

Use the built-in `GITHUB_TOKEN` only in the release-creation step. Create a non-prerelease release named/tagged exactly from `vX.Y.Z` and upload the installer plus checksum manifest. No release-creation step may run after a failed package or audit step.

- [ ] **Step 5: Document release tagging**

Update `RELEASE_CHECKLIST.md` with: merge reviewed changes to `main`; create and push the next version tag only when ready for learners; wait for Windows build/audit; inspect release assets; then confirm the installed app detects it. State that no web hosting account or model API key is required for publishing.

- [ ] **Step 6: Manually verify workflow behavior**

Inspect the workflow definition and a successful release run; confirm an ordinary main commit produces no installer release, a valid version tag publishes assets, and a simulated build/audit failure stops before release creation. Do not push a production version tag during this task.

## Task 6: Update Public Installation Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/PROJECT_INTRO.zh-CN.md`
- Modify: `docs/PROJECT_INTRO.en.md`
- Modify: `RELEASE_CHECKLIST.md`

**Interfaces:** Documentation must describe the same package names, app name, local data paths, key persistence behavior, update cadence, formal tag trigger, and unsigned beta limitation as the app and workflow.

- [ ] **Step 1: Write the Chinese install/update guide**

Explain downloading the public installer from GitHub Releases, WebView2 prerequisite, the first-run empty progress state, local progress retention, optional personal API key and provider charges, launch-time/six-hour update checks, visible install/restart, and unsigned publisher warning.

- [ ] **Step 2: Align English docs and project introduction**

Translate the actual supported behavior rather than promise immediate push, silent install, account sync, or a bundled API. Keep the Chinese documentation primary.

- [ ] **Step 3: Reconcile release audit and repo instructions**

Document which files go into the installer, confirm `.env` and local data stay out, and keep `sources/` read-only. Do not edit anything under `sources/`.

- [ ] **Step 4: Review user-facing claims**

Compare README, project introduction, installer prompts, model settings, and updater prompt against the design spec. Remove claims that an unsigned SHA-256 proves publisher identity or that the app receives push notifications while closed.

## Manual Verification and Completion

- Source-mode browser app still starts using the existing batch launcher and continues using the local `.env` only in developer mode.
- Desktop install starts a loopback-only FastAPI service, opens a standalone window, and exits cleanly.
- Clean install creates public learning content but no prefilled user progress; upgrades preserve each Windows account's progress and optional saved API key.
- API key never appears in config JSON, API responses, installer files, updater logs, or GitHub assets.
- Only a valid formal version tag creates a public release; a failed workflow leaves existing published releases untouched.
- Update checking does not block offline learning; only verified assets are presented; installation requires an explicit click and uses a visible installer.
- Manual checks only; no automated tests are added or run under the current task instructions.
