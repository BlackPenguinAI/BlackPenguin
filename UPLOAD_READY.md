# BP-HERMES-P07 · Upload Ready differential

This archive contains complete changed/new files in **BlackPenguin repository-relative paths**. Extract it and upload the directory contents via GitHub **Upload files**; do not upload the ZIP itself as a repository file.

Baseline: `BlackPenguinAI/BlackPenguin` `3df05579e36524eb51b225b45174546f4615f6d7` (P05/P06). No code must be run before upload. No GitHub or production server change has been performed by the package creator.

- P07 SDK registered-tool allowlist enforced and checked; callbacks for disabled tools reject invocation even if bypassed.
- P07 pinned SDK toolset-cache isolation and tests, P05 fixture import isolation.
- 3 new isolated PostgreSQL acceptance tests included in existing predeployment Postgres runner.
- Existing production LangGraph Sales Core and outbound providers remain unchanged.
- No new migration and no live-runtime activation.

**Local result:** 181 Python tests PASSED; 3 PostgreSQL-only tests SKIPPED locally because no PostgreSQL server is available. The new GitHub predeployment PG gate must run **14/14, 0 skipped** before accepting this release. Live SDK/OpenRouter, real provider delivery and multi-company E2E remain NOT RUN (see `P07_ACCEPTANCE_REPORT.md`). Do not treat P07 as approval to perform P08 cutover until all blocking tests are verified.

Suggested commit: `test(hermes): enforce published tool policy and add PostgreSQL P07 gates`
