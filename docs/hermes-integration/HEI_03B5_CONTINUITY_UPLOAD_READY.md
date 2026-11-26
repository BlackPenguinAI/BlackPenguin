# HEI-03B.5 — Continuity & Scheduled Work

Base: `84688c2f064c184b59b326c192d7d34939ab305c` (2026-11-26).
Deployment: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45837268895 (success).
Commit: `feat(hermes): integrate scoped resume and deterministic scheduled work`.

## Scope

Hermes is still disabled for live selection by `live_hermes_ready() == False`. LangGraph and its admin config remain intact. This delta changes the existing sales worker and provider authorization only; no schema migrations, public API routes, deployments, credentials, or onboarding changes. It is a candidate, not a live provider certification.

### Resume

- Scheduled job has its own `resume:<job.id>` engine pin. It must match the current opportunity and control epoch. Consent, project approval and provider route are checked again, as is absence of an open intervention.
- For one untouched, authenticated, currently pending original inbound, preserve its actual `SalesMessage` and provider ID. Requeue its existing `SalesInboundJob` if awaiting resume, or create the missing job if the message arrived while paused. The resume job records `hermes_resume_requeued` and IDs; that status means **requeued**, not answered.
- Never create a synthetic provider message. Never overwrite a conflicting original engine pin; preserve previously pinned Hermes policy. No previous AgentRun, intervening outbound or outbox, deterministic control, already handled message, mixed input set or conflicting active work may pass this lane. Those cases require reconciliation; no automatic fallback.
- Flush before the existing `queue_resume` queries pending inputs (production `SessionLocal` disables autoflush), to capture newly marked inputs in the epoch.
- Live preparation invalidates previous choices, booking/cancellation/replace proposals and material offers when the latest assistant reply does not belong to the current Hermes control epoch (or takeover barrier exists without a latest reply). Keep focus and permanent preferences; preserve immutable operation records. This is applied when preparing a new live turn, not a new DB migration or immediate rewrite on takeover.

### Scheduled work

- After the accepted final reply, if an active visit or manual control does not prevent it, schedule at most one inactivity close and one follow-up for that answered episode. Reuse existing Staff timing values and operating-window functions. Follow-up uses a neutral deterministic question with STOP instruction; no inference, property assertion, or commercial effect. No recurring follow-up chain until new buyer activity. Inactivity uses the existing `continuity.CLOSING` text.
- Each scheduled job stores the current scope, epoch, original inbound ID, final accepted response ID, exact Hermes pin at enqueue time, expiration and independent idempotency key. Legacy unscoped cadence is not silently adopted. If another engine is selected, do not transfer the pinned job to it.
- Both proactive sends require current permission, no open intervention, active approved project, no unresolved input, no active visit, matching episode, a real accepted outbound correlated with a completed Hermes run, no held commercial policy, due time and allowed contact window. WhatsApp requires the existing 24h customer window. Inactivity expiry is 15 min after due; cadence expiration is 24h after its scheduled time. Cadence may defer until the allowed window if not expired.
- A new `hermes-scheduled/1` delivery identity uses the shared `_dispatch`, with authorization both before outbox persistence and immediately before the provider request. No fictitious AgentRun. Reconciliation uses the exact single-part outbox/message pair, provider IDs, scope, content and job identity. `queued`/`sending` receipts with a valid provider ID wait for the existing webhook update; up to ten pending receipt checks. Unknown, rejected or inconsistent receipts go to review, no automatic resend. If a previously sent episode is superseded, retain existing outbox for review instead of creating another message.
- Recover interrupted Hermes scheduled cadence claims with the existing stale-claim scan, in addition to resume and inactivity. No change to legacy cadence claim recovery.
- Scheduling errors for invalid timing or unavailable governance window are recorded as `hermes_scheduling_status=review` without undoing a completed inbound reply. Other unexpected errors still require review.

## Files

New: `backend/app/modules/hermes_sales_core/scheduled_work.py`, `backend/tests/test_bp_hei03b5_scheduled_work.py`.
Modified: `live_job.py`, `live_preparation.py`, `provider_delivery.py`, `sales_agent/engine_router.py`, `sales_agent/live_worker.py`, `sales_agent/live_service.py`, `sales_agent/continuity.py`, `services/hermes_worker/sdk_smoke.py`.
Reincluded: `.github/workflows/hermes-sdk-smoke.yml` (absent in base tree). Documentation: this file.

## Evidence

Source and Python 3.12.16 environment extracted from GitHub Actions release API artifact 15126951259 for the exact base SHA. Internal `api.sha256` verified. All 7 modified backend originals, previous 8 HEI test suites and SDK smoke original were checked against git blob hashes. Prior tests restored from the prior ZIPs (exact hashes). Used synthetic SQLite in-memory databases, real ORM/dispatcher, deterministic SDK and provider doubles, no real credentials. Actual full repository CI and real SDK/provider inference NOT run locally.

Local command (test-only env and SQLite): `python -m pytest -q tests/test_bp_hei*.py --disable-warnings`.
Result: **267 passed, 1194 warnings in 26.52s**. Prior 241 + 26 new. All new tests pass, including no-job resume, original job requeue, legacy pin rejection, existing run/outbox rejection, multiple-input review, scope/epoch/opt-out/new inbound/expired/switch rejection, no duplicate follow-ups or model call, queued receipt reconciliation and pre-provider reauthorization. The warnings are not a pass for the external integration; investigate in full CI.

## Remaining gates / limitations

- Multi-message resume with a single response covering all pending inputs, prior attempted/reconciled runs, handoff receipts and ambiguous episodes require explicit handling. Do not auto-replay them or treat requeue as answer.
- Conversational multipart replies still have single-part state receipt constraints. Material delivery may use multipart groups from prior implementation. External URL galleries remain pending.
- Existing legacy cadence before a genuine Hermes response is not adopted. The new cadence is intentionally one follow-up per answered episode rather than a recurring nurture campaign or new model-based prompt. Staff timing is reused, but copy is deterministic and not a new configurable Hermes prompt.
- Real private SDK service not deployed; standalone import workflow still absent in base. No live readiness toggle; actual SDK build, inference, external Telnyx and Calendar, PostgreSQL concurrency and full regression still need HEI-06/07. The next work should close remaining resume/multipart contracts and test across engines before final certification. Inspector work can use actual receipts without pretending these cases are complete.

## Upload

Extract ZIP, upload folders `backend`, `services`, `docs`, `.github` at repository root https://github.com/BlackPenguinAI/BlackPenguin/upload/main. Commit as above. No pre-upload script. Verify both ordinary deployment and standalone Hermes SDK smoke in Actions. If `.github` was skipped, upload the separate `hermes-sdk-smoke.yml` at https://github.com/BlackPenguinAI/BlackPenguin/upload/main/.github/workflows. This workflow builds/imports the pinned SDK only; no model calls and no external sends.
