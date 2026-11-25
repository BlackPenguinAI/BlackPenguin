# BP-HERMES-P08 · Controlled migration readiness (NOT live cutover)

Baseline inspected: BlackPenguin `0ef0c23a4a96fa61763f22d23a64c7a0de83d9bc`, 25 November 2026. Its commit message references P07, but GitHub returns **zero changed files** and zero associated workflow runs: P07 has NOT actually been applied. This package **re-includes the P07 changed/new files** (complete files) in addition to P08.

## What this package adds

- `p08_simulation.py`: a strict, test-only transactional Hermes turn runner using existing P04 draft tools and P03 durable state receipts. A simulation lead must have prior consent; each saved assistant reply exactly matches the model output and is linked to the persisted inbound, global published version, and Hermes state event. Retries return the same reply without a new SDK call. Neither providers nor Calendar are called by this runner.
- `services/hermes_worker/`: a pinned Nous Research SDK Docker image separated from the BlackPenguin API image. It runs the simulation-only CLI in a dedicated **test/staging** DB. No HTTP listener is exposed; the DB name must include `test` or `staging`. Hermes home is writable and the process is non-root.
- `.github/workflows/hermes-p08-staging.yml`: isolated SDK import and CLI safety checks in a separate no-deploy CI job. Its result MUST be checked before using the container.
- P08 tests for exact outbound/state receipts, idempotency, denied live channels, consent, human takeover, rollback and orphaned output.

## Current release gates: NOT READY

1. **P07 content recovery:** confirm a *non-empty* GitHub commit containing `backend/app/modules/hermes_sales_core/runtime.py`, `backend/tests/test_bp_hermes_p07_*` and `backend/tools/sales_ai/postgres_checks.py`.
2. **Production CI:** `backend-regression` shards, `sales-acceptance`, `verify-regression`, and `build-frontend` all pass on the exact commit SHA.
3. **P07 PostgreSQL:** original 11 plus new 3 PostgreSQL 16 acceptance tests must pass **14/14; zero skipped** in isolated infrastructure.
4. **Hermes SDK:** the dedicated P08 smoke workflow must PASS on the same commit. This tests import compatibility only—not paid OpenRouter inference.
5. **OpenRouter real integration:** run a dedicated staging DB and pinned SDK worker against genuinely approved project inventory, ordinal follow-ups, state reconnection and a human approval boundary. NOT RUN in this delivery.
6. **Commercial effect certification:** valid reservations, cancellations, reschedules, approved material share receipts, advisor assignment, Google Calendar retries, and Telnyx/Twilio provider receipts with real idempotency. The existing P04 effect executor is **simulation-only**, so this remains BLOCKED.
7. **Production rollout and rollback:** distinct Hermes worker deployment, signed/internal job transport, per-conversation engine ownership, no duplicate messaging on retries, an auditable reversible migration plan and tenant isolation load test. NOT IMPLEMENTED or validated here.

**Do not delete `sales_agent` or `langgraph` dependencies and do not route live inbound jobs to Hermes yet.** These are safety-critical production systems and the P08 staging runner makes no claim to replace them.

## Upload instructions

Unzip and upload the **contents**, retaining repository-relative paths. No pre-upload shell commands or patch application are needed. Prefer a branch; `main` triggers a production deploy for the existing application (the SDK staging image is built only, not deployed).

## Local verification

`pytest tests/test_bp_hermes_p*.py`: 193 passed, 3 PostgreSQL-only skipped (hermetic SQLite/test doubles). The SDK import/build, OpenRouter and providers were not available to test locally and remain NOT RUN. CI should furnish independent evidence for each.

## Next precise milestone

Once P07 and the isolated SDK smoke are green, implement a real outbound-safe Hermes worker and production effect receipts with the same safety properties as the existing sales worker. Only then conduct an explicit, auditable tenant-independent cutover after staging E2E approval; retain old historical records but retire the legacy engine code after proving cutover, rather than deleting it ahead of evidence.
