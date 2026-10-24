# Windows desktop distribution design

## Goal

Ship the public AI PM Learning Compass as a Windows installer. A learner installs and opens a standalone app window, configures their own model provider and API key, and keeps their learning data on their own computer. Maintainers publish an update by pushing a change to the repository; users receive an in-app update prompt the next time the app checks for releases.

There is no separate product website, user account service, shared model API, or hosted learning database in this release. GitHub is used for source hosting, build automation, and installer downloads.

## Decisions

- Windows desktop app in an independent window, using pywebview to host the existing local FastAPI application and static UI.
- Package the Python runtime and app with PyInstaller; create a per-user Windows installer with Inno Setup.
- On every successful push to `main`, GitHub Actions builds a clean installer and publishes a GitHub Release. A failed build must not publish or advertise an update.
- The app checks GitHub Releases on launch and periodically while open. When a newer release is available, it downloads the installer, verifies its SHA-256 against release metadata, then asks the learner to install and restart. It does not force-close the app or install silently. There is no notification while the app is closed.
- Every new installation starts with an empty learning database. Each learner's SQLite database remains in their Windows user profile and is preserved during app upgrades. Uninstall leaves learning data and preferences in place by default; the app offers a separate explicit action to remove them.
- The learner supplies and pays for their own model API. Requests go from the local app directly to their chosen HTTPS provider.
- API key persistence is optional. If “remember this device” is selected, store the key using Windows Credential Manager; otherwise keep it in process memory only. Provider and model preferences may be stored in a per-user config file under `%LOCALAPPDATA%`. Clearing model settings removes the saved key and runtime configuration.
- The installer contains no `.env`, API keys, SQLite databases, learning records, browser profiles, or local caches. CI must build from a clean checkout and must not package local working-directory data.
- Initial public beta installer is unsigned. Windows may display an unknown-publisher or reputation warning. Code signing can be added later if distribution needs justify the certificate cost.

## Application layout and data flow

The desktop launcher starts the local FastAPI server bound only to `127.0.0.1` on an available local port, waits for its health endpoint, and opens the pywebview window. The server shuts down when the desktop window exits. It must not expose a network listener to other devices.

All writable user data moves out of the installation directory:

- SQLite learning history and progress: `%LOCALAPPDATA%\AI PM Learning Compass\data\app.db`.
- User preferences and update state: `%LOCALAPPDATA%\AI PM Learning Compass\config`.
- Downloaded installers: a temporary per-user update directory; remove incomplete or verified-and-installed files safely.
- Optional API key: Windows Credential Manager, addressed by an app-specific credential target.

The installer has no seeded learner database. On first run, the app initializes the schema and inserts only public curriculum/catalog content required for normal operation. It must not include the maintainer's local database or progress. Upgrades replace application files only and never overwrite the user data directory.

## Build and release flow

1. A push to `main` starts a Windows GitHub Actions workflow.
2. The workflow installs dependencies from a committed lock file, packages the desktop launcher and app resources, runs a dedicated privacy audit against the actual staged installer payload, produces the installer, and emits SHA-256 metadata. This payload audit is separate from the existing Git-index/history leak audit.
3. Only after all packaging and audit steps succeed does the workflow publish a versioned GitHub Release and attach the installer and checksum metadata.
4. The running app queries the public latest-release endpoint, compares the release version with its packaged version, downloads the asset, checks the checksum, and presents the install/restart prompt.
5. The updater starts the downloaded installer in per-user update mode, waits for the installation to complete, then relaunches the app. User data stays in `%LOCALAPPDATA%` throughout.

Version identifiers must be unique and monotonically sortable across `main` pushes (for example, a maintained version plus the GitHub Actions run number). A release cannot be replaced by a failed or partial build. The release endpoint and asset names are part of the app/updater interface and must be treated as stable.

## Failure handling and safety

- If GitHub is unavailable, the app continues offline and reports that update checking could not complete; it does not block learning.
- If the release endpoint returns malformed metadata, no update is installed.
- If download or SHA-256 verification fails, discard the partial file and keep the current app running.
- If installation fails, preserve user data and show a retry/download link. Do not delete the current installed version before the replacement is ready.
- If the app is already running during update, the updater requests a normal close only after the learner accepts; it relaunches after success.
- Use GitHub's repository-scoped workflow token only in Actions; no personal access token is embedded in the app or installer. The public app reads public release metadata without a token.
- Because the first installer is unsigned, label the download as an early public beta and explain the Windows publisher warning in release instructions. Do not claim that checksum verification establishes publisher identity.

## Scope

Included: desktop window, per-user installation, local data path, optional Credential Manager key persistence, main-push build/release automation, app update checks/download/checksum/prompt/restart, Chinese-first installation and update messaging.

Excluded: separate marketing or update website, hosted accounts/sync, shared API service, silent or forced updates, mobile/macOS/Linux installers, automatic data deletion on uninstall, code signing in the first beta.

## Acceptance criteria

- A clean Windows install opens the app in its own window without requiring a separately installed Python environment.
- A first install has empty learner progress even when the developer machine has local data.
- Two Windows accounts use separate learning databases, settings, and optional API key vault entries.
- An app upgrade preserves the same Windows user's progress, settings, and saved key.
- The app does not send the learner's API key to this project's server or GitHub; requests go to the selected provider.
- A successful `main` push creates a downloadable installer release; a packaging/audit failure creates no release.
- A running older app detects a newer release, downloads it, verifies the published checksum, prompts before installing, and relaunches after update.
- Offline update checks, invalid metadata, interrupted downloads, and failed installs do not prevent the existing app from opening or destroy user data.
- The installer payload and release audit contain no `.env`, private database, local learning records, or embedded API secret.

## References

- [GitHub Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [pywebview installation guide](https://github.com/r0x0r/pywebview/blob/master/docs/guide/installation.md)
- [Microsoft WebView2 distribution](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution)
- [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html)
- [Inno Setup](https://jrsoftware.org/isinfo.php)
- [Windows Credential Manager guidance](https://learn.microsoft.com/en-us/windows/win32/secbp/handling-passwords)
