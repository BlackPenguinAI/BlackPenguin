# BlackPenguin Hermes — P07 validation and readiness report

**Target repo:** `BlackPenguinAI/BlackPenguin`

**Repository baseline:** `3df05579e36524eb51b225b45174546f4615f6d7` (P05/P06 commit on 2026-11-25). The associated GitHub Actions deployment workflow completed successfully, run `45680629142`.

**P07 result at packaging:** **PARTIAL / NOT CLEARED FOR P08**. Offline acceptance tests pass, but connected SDK, live providers and real-PostgreSQL P07 tests have not been executed in this workspace. No Hermes production cutover is authorized by this release.

## Scope of this differential

1. Enforce the Staff-published Hermes tool allowlist **in the SDK registry, loaded tool list, and handler**, without relying on the system prompt for permissions.
2. Reset the pinned Nous SDK's cached toolset-level availability check safely between calls. Do not deregister tools owned by another toolset. Pinned SDK: `b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb`.
3. Optionally propagate the selected tool set through both isolated preparation functions (`prepare_offline_turn`, `prepare_p04_simulation_turn`). Existing callers remain compatible.
4. Repair the P05 test fixture's module import isolation when combined with earlier Hermès SQLAlchemy fixtures. Production ORM and migrations remain unchanged.
5. Extend the **already existing, predeployment isolated-PostgreSQL check** from 11 to 14 required test cases. Three new tests exercise P03 state/revisions, competing writers and the P04/P05 migration round-trip in separate random schemas.

## Executed evidence

| Gate | Status now | Scope/evidence |
| --- | --- | --- |
| Existing P01–P06 tests | **PASS** | All 170 preexisting tests in reconstructed differential environment |
| P07 SDK policy + registry cache tests | **PASS** | Offline fake SDK; includes disable-all then re-enable, stale policy, toolset collision and hard handler denial |
| P07 published-version pinning | **PASS** | Model/prompt/tool version frozen per turn; rejected missing key |
| P07 simulation preparation | **PASS** | Both offline and P04 preparation accept an explicit frozen allowed-tool set |
| P07 combined Python suite | **PASS** | **181 passed, 3 skipped** using local Python/SQLAlchemy/SQLite |
| Actual PostgreSQL P07 races + migrations | **NOT RUN locally** | No PostgreSQL service in this workspace; the new predeployment gate runs these in a disposable PostgreSQL 16 container **after upload** |
| Full existing backend CI shard suite | **NOT RUN on P07 commit** | GitHub Actions must run after upload |
| Angular production build with P07 commit | **NOT RUN on P07 commit** | No Angular files changed by P07; P05/P06 baseline GitHub run passed |
| Real pinned Hermes SDK invocation | **NOT RUN** | Requires isolated `hermes-agent` runtime and a controlled SDK smoke test |
| Live OpenRouter | **NOT RUN** | Requires staging credentials, spend limits and explicit permission |
| Real Calendar writes | **NOT RUN** | P04 operates only in simulations; authenticated staging account and rollback required |
| SMS/WhatsApp provider acceptance and actual delivery | **NOT RUN** | P08 rollout prerequisite; do not use customer contacts for P07 |
| Real load/FIFO/distributed worker recovery | **NOT RUN** | P08 queue wiring/worker deployment is not built yet |
| Cross-tenant live black-box E2E | **NOT RUN** | Need staging multi-company accounts/fixtures and real BP database |

Counts in the table distinguish simulated contract tests from **real external integration**. Skips do **not** count as passes. The three P07 PostgreSQL tests are excluded from the local passing count and are mandatory in the updated GitHub predeployment PostgreSQL acceptance script.

## Important findings

- **F-01 — global tool restrictions not enforced in P01–P06 runtime.** Fixed in `runtime.py` using explicit `enabled_tools`; unknown permissions reject construction; disabled handlers return `GLOBAL_TOOL_DISABLED`; the SDK-discovered names must exactly match the allowlist or the turn fails closed.
- **F-02 — pinned Hermes registry caches its first check_fn as a toolset check.** Fixed: re-register only tool names owned by this toolset each turn, registering allowed names first. Empty -> permitted transitions cannot inherit a false cached toolset gate.
- **F-03 — combined P05 fixture could map the wrong SQLAlchemy Base.** Fixed in the P05 test fixture using `importlib.import_module` after clearing the relevant module cache. No production model changes.
- **F-04 — real PostgreSQL gap.** Added a gate in the existing isolated PG predeployment harness; do not infer success until GitHub Actions reports 14/14, zero skipped.
- **F-05 — Hermes is not connected to the real inbound/outbound pipeline.** Correct and intentional until P08. Staff `enabled=true` alone is **not** a release switch.

## P08 release blockers — all must be positively validated

- Actual pinned Hermes SDK loads the selected global tool policy (no extra tools); no unapproved tool invocation reaches commercial services.
- Real PostgreSQL 16 P07 tests pass; exercise migrations against a disposable environment matching production schema version.
- Real two-company/two-project authorization checks, with forced ID substitution attempts, cannot access or modify another tenant.
- One exact confirmed appointment yields one durable receipt, one advisor, correct project timezone and no duplicate calendar event after retry.
- Reprogramming preserves original reservation on failure; cancellation affects only the selected lead's appointment.
- Material shares use approved coverage and expiring scoped links, and do not claim a send without a provider receipt.
- One inbound yields at most one accepted outbound, in FIFO order even under replay, restart and duplicate webhooks.
- UI formatting and `option 2` reference in Agent, Monitor and Schedule are verified using actual rendered dialogue.
- Provider acceptance, delivery, failures and uncertain receipts are represented distinctly.
- Alerting, rollback and staged cutover procedure are verified without replacing current LangGraph logic prematurely.

## How the new PostgreSQL gate works

`backend/tools/sales_ai/postgres_checks.py` remains the predeployment runner already used by `.github/workflows/deploy.yml`. It now mounts and runs `test_bp_hermes_p07_postgres.py` alongside the original five Sales PostgreSQL modules. It requires **14** JUnit test cases with no failure or skip. The runner creates its own internal Docker network, randomized password and disposable PG16 instance; the P07 module additionally creates a uniquely named schema and deletes it afterward. It never uses production `.env`, remote PostgreSQL, customer messages or calendar providers.

**The P07 gate is designed to fail the production deployment before activation if these 3 PostgreSQL tests fail.** It cannot certify real OpenRouter/Calendar/Telnyx integrations; those remain separate blockers.
