# HEI-03B.6 — Remaining Conversation Contracts

## Upload Ready

Base: `5c58f3bc5d430a6e1303bc7fc269981fa6de27b2` (main). Deployment workflow [45854330288](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45854330288), completed successfully.
Commit: `feat(hermes): complete guarded resume batches and conversation delivery contracts`.
Extract this archive and upload the complete repository-relative files via GitHub Upload Files. Do not apply a patch, run an installer, modify DB schemas or change production environment variables. Include `.github/workflows/hermes-sdk-smoke.yml` (hidden directory); if omitted, use the individual workflow download and upload it to that directory. The prior main tree did not contain this workflow. Check both the standard deployment and independent SDK smoke.

## Implemented behavior

- **Resume batches:** release 1–10 contiguous, untouched, authenticated originals, each <=4,000 characters and aggregate <=12,000 UTF-8 bytes; retain all original IDs. Only the newest message is the anchor for the single AgentRun; earlier pending inputs are provided as chronological history, not new authorization. Pin content hashes, IDs, provider IDs, policy version, opportunity, episode and control epoch. Validate all sources when reserving, preparing, authorizing provider sends and reconciling. Mark all original inputs handled only after the accepted reply; earlier existing waiting jobs become superseded. No manufactured provider messages.
- **Multipart informational replies:** up to four exact provider parts, 4,000 characters total; 1,400 characters SMS or 3,500 WhatsApp per part. Immutable draft and hashes are matched to actual scoped OutboundMessage/SalesMessage receipts. Persist one state revision only after all parts are accepted; queued sends poll existing receipts. Use actual last part as completion anchor and store ordered message IDs. No synthetic full-message row or fabricated provider receipt. Clear old transient proposals. Actionable menus, appointment recaps and commercial mutations still require a single intact provider message; partial or uncertain groups require staff review, not automatic resend.
- **External galleries:** URL-only approved gallery assets can issue distinct opaque accesses for reviewed HTTPS links with kind `photos` or `gallery_image`, up to 20 resources per material batch. Existing local files take precedence. Use existing asset snapshot, asset sharing, dispatcher and receipt services. Never fetch remote gallery URLs on the server. No raw URL or bearer token in Hermes operation/state/diagnostic JSON; customer receives the opaque access link. Existing outbox metadata retains exact approved binding. Resolve validates matching outbox, message, plan, token hash and live approved binding on access. Removed or changed gallery targets are denied even after an engine switch. This change affects only external shares tied to a live Hermes run.
- **Engine transition:** first routed Hermes inbound records engine ownership in the existing continuity JSON. Subsequent routed transitions advance the control epoch (or reuse the already-advanced authenticated resume epoch), invalidate temporary authorizations, cancel pending old scheduled work and clear old LangGraph proposals when returning to LangGraph. Historical receipts and permanent preferences remain. Reject an existing event that would cross an intervening engine boundary and scheduled work from the superseded engine. Legacy-only opportunities remain unchanged. This is an inbound-router boundary, not a global backfill or bulk migration. Direct historical entrypoints outside the router remain an activation-audit concern.

## Regression

Downloaded API artifact `15135176761` from the successful run; ZIP SHA-256 matched `771593859684a3c4e102f1e106b8bba1432179bd686f870f0f323ea6c031fa6e`. Extracted actual application code and Python 3.12.16 dependencies from the deployed image. Original modified source blobs and modified previous test matched GitHub. Used isolated SQLite and synthetic environment settings, existing ORM, native materials, shared dispatcher and simulated provider/SDK. No remote requests to production, OpenRouter, Telnyx, Google Calendar or PostgreSQL. No general BlackPenguin suite executed locally.

Local focused regression: `284 passed, 1529 warnings in 29.91s` (267 prior cases including an updated rejection for a malformed multi-input batch; 17 new cases). New tests cover genuine batch with/without older job, changed input/content/provider/scope/epoch/newer inbound/manual handling, queued group without duplicates, all-parts state commit, actionable multipart rejection, tampered part, gallery issuance and invalidation, engine transition and scheduled boundary, actual preparation history. Run in an isolated test environment with the normal BP requirements and fixtures: `pytest -q tests/test_bp_hei*.py --disable-warnings` from backend. Full suite and SDK Docker smoke require CI.

## Remaining gates and known limits

- No actual SDK/OpenRouter or real provider calls, PostgreSQL contention checks or Calendar effects certified. The hard `live_hermes_ready()` gate remains false and the private SDK service is not deployed by this package. Never flip readiness simply because the standard CI deploy succeeds.
- Resume involving any prior run, attempted outbox, non-contiguous episode, changed source or mixed policies stays in review; no automatic replay of a partially executed old turn. Provider-part uncertainty is handled conservatively. Full cross-part actionable menu/recap support remains an explicitly unsupported case. External galleries are limited to approved HTTPS targets attached to URL-only gallery assets (local files use the established local path). No broad CRM migration or legacy engine replacement. The boundary is activated by routed inbound events; other entrypoints need audit before cutover.
- HEI-03 main commercial flows are implemented with documented safe boundaries. Next phase HEI-04 Conversation Inspector should expose real receipts and review reasons. Remaining edge cases and provider/SDK certification belong to HEI-06 acceptance gates, not an assumption of production readiness. HEI-05 must preserve LangGraph configuration and staff controls; activation remains HEI-07.

## Baseline blob hashes

- `asset_share_service.py`: `0c09a2c0d89f37f815d54f695292d00807cda0b2`
- `engine_router.py`: `1e066312b5ff4ddbad170da7cd4cef9aca242532`
- `live_job.py`: `9eac7fa646555a45194c75a602decd2168ab3937`
- `live_materials.py`: `84107106776af64bb0af6e97209a60012fcae79d`
- `live_preparation.py`: `943f76712fb6a8aa69b742388446f184929c1645`
- `live_receipts.py`: `072a9049d9795185efcc6c528707709423f4374e`
- `production_tools.py`: `7aacce37c24ff6b29b2093f334d4664742a1f0d3`
- `provider_delivery.py`: `83c6e5200214e7e235ac4dbd1103e9ec4f56609b`
- `scheduled_work.py`: `1aa253eb69c51cb9dbc75423018c75667dbb3a7a`
- `test_bp_hei03b5_scheduled_work.py`: `04bbd090251af738d4aa28a808fbf578f77d0448`
- `sdk_smoke.py`: `759aac81d35435ee09d5dab12d19d29d9476402f`
