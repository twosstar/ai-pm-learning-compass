# Windows release checklist

The public repository update and a learner-facing app release are separate actions. Ordinary commits and merges do not publish an installer. A formal release starts only when the maintainer pushes a new `vX.Y.Z` tag on a commit already reachable from `main`.

## Before creating a release tag

- [ ] Review curriculum authorship and redistribution scope; keep `sources/` read-only.
- [ ] Confirm public curriculum, concept cards, screenshots and bundled files contain no private course material or learner records.
- [ ] Confirm `.env`, local databases, logs, browser profiles and user data are absent from the installer payload.
- [ ] Review source changes and release notes; confirm the target repository is `twosstar/ai-pm-learning-compass`.
- [ ] Confirm the new `X.Y.Z` version is greater than the latest stable GitHub Release.

## Publish a formal release

1. Merge the reviewed code to `main`.
2. Create and push the next version tag only when the installer is ready for learners, for example `v1.0.0`.
3. GitHub Actions builds the Windows installer, audits the staged payload, and stops if either step fails.
4. Inspect the published Release. It should contain only `AI-PM-Learning-Compass-Setup-X.Y.Z.exe` and `SHA256SUMS.txt`.
5. Install the release on a clean Windows account and confirm it opens, starts with empty progress, and retains progress after a restart.
6. Confirm a later formal release is detected in-app and requires the learner to choose “安装并重启”.

No website hosting account or shared model API key is required. Each learner configures and pays for their own model provider. Beta installers are unsigned and may show a Windows unknown-publisher prompt. The checksum detects damaged downloads but does not identify the publisher.

The installer includes the app executable, public curriculum/concept JSON, static UI, and updater helper. Learning records and model settings remain in `%LOCALAPPDATA%\AI PM Learning Compass` and are not bundled. Uninstall intentionally leaves that user data in place.
