# Public release checklist

- [ ] Confirm authorship or redistribution permission for every source file and text asset.
- [ ] Review the public sample curriculum and concept cards for similarity to paid-course outlines or explanations.
- [ ] Confirm stable knowledge-point IDs and public syllabus mapping; do not export a private course database.
- [ ] Confirm `.env`, local databases, logs, browser profiles, and course files are ignored and absent from the release tree.
- [ ] Confirm page-entered model keys are runtime-only and settings return no key; do not expose this local app as a public multi-user key service.
- [ ] Run `python scripts/release_check.py` and the automated tests.
- [ ] Review dependency licenses and select a project license only for material you have authority to license.
- [ ] Inspect the final staged file list and repository diff.
- [ ] Confirm the repository target and project license before publishing; launch copy and screenshots in `docs/` are candidate materials, not proof of deployment.
- [ ] Verify progress/draft recovery with temporary data, and ensure all published screenshots contain demo data only.
- [ ] Create or update a GitHub repository only after this review. Do not push automatically.
