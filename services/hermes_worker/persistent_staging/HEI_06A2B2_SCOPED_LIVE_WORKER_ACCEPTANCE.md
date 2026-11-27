# HEI-06A.2b.2 — Scoped Live Worker Acceptance

**Base:** `38affaa86c36bb60e13eaa99a670bfdc70ff827b` (scoped simulation acceptance).  
**Scope:** hosted CI, actual inbound queue, actual worker claim and routing callback, private SDK preparation, shared dispatcher, simulated SMS provider receipt, native Hermes state and inspector.  
**Production readiness:** CLOSED.  
**Status:** implementation and local focused tests complete; cross-container integration NOT_RUN locally.

## 1. Purpose and limits

The previous stage proved the isolated simulation queue and in-app receipts. This stage exercises the actual `SalesInboundJob`, not a second commercial queue. It does not activate Hermes for ordinary API traffic.

The certified API's continuous worker is deliberately stopped while a dedicated non-root one-shot worker owns the queue. That process invokes `live_worker._claim_inbound_jobs`, `_isolated_job` and `_routed_inbound_job`, which reach the original `route_live_job`, `process_hermes_inbound_job`, `run_job` and dispatcher. The original API and closed SDK service are restored before the HTTP inspector checks.

**Explicit limitation:** the process composition uses `unittest.mock.patch` to inject a task-scoped authorization adapter into the existing imported readiness functions, a narrow resolver into `engine_router.resolve`, and a fake SMS transport. It does not modify the global `live_hermes_ready()` flag or source files in `backend/`. It is an acceptance harness, not a permanent runtime authorization contract for the continuously scanning API worker. The endpoint wrapper first checks the exact reserved job and run, then invokes the original `sdk_service.prepare`. The actual runtime and tools are unchanged in the model lane; the offline lane substitutes only `HermesSalesRuntime.process_turn`. No webhook intake, real sender registration, scheduling, appointment, media or CRM effects are authorized. Full continuous-worker authorization, real providers, production rollout and rollback remain NOT_RUN.

This is intentionally narrower than opening a global readiness flag or copying the isolated simulation queue into production. The remaining work is to turn this job-scoped contract into a reviewed normal-runtime integration without test composition hooks.

## 2. Responsibility parity with the demo

Reference: https://github.com/jorgektch/testing-hermes-agent (the previously reviewed v13.3.3 architecture). Hermes owns interpretation, reasoning, tool selection and reply construction. BlackPenguin owns the approved catalog, authorization, FIFO queue, execution, provider acceptance, receipts and persistence. No changes to the SDK runtime, prompt, search semantics, choice resolution, monetary policy, or LangGraph are made.

Source components reused at the certified base:

- `sales_agent/live_worker.py`: claim and inbound callback.
- `sales_agent/engine_router.py`: stable event pin and original decision contract (`_decide`).
- `hermes_sales_core/live_job.py`: reservation, HTTP preparation, delivery and reconciliation.
- `hermes_sales_core/sdk_service.py`: internal auth, private request, existing draft path.
- `hermes_sales_core/live_preparation.py`, `live_coordinator.py`, `live_receipts.py`: existing draft and state receipts.
- `sales_agent/live_service.py` and `hermes_sales_core/provider_delivery.py`: unchanged dispatcher and exact delivery authorization.

The workflow verifies the original production baseline and the exact Git blob hashes of key entry points. No production source is patched on disk. Normal API routing stays LangGraph; no fallback is permitted in the one-shot test lane.

## 3. Scope and lease

A separate synthetic company/project/lead/conversation is seeded only after verifying the staging database marker and the candidate SHA. The lead is `is_test=True` and project/lead are `is_demo=False` solely because the existing live path rejects demo records. These are fictitious fixtures in the isolated database, not actual customer records. The synthetic SMS sender has no real provider route or credentials.

Grant: 30 minutes; fixed company `stg-live-company`, project `stg-live-project`, lead `stg-live-lead`, conversation `stg-live-conversation`; `sms` channel and synthetic recipient `+15550000003`; model `openai/gpt-4o-mini`; policy must be published, enabled and contain exactly `get_project_overview` and `get_unit_details`.

Only three fixed messages exist: first (bedrooms in Van Buren), second (bathrooms in Van Buren), revoked (project name; never inferred). No arbitrary input or provider request endpoint is exposed. A `ContextVar` capability is bound to the current job and reset after use. The gate verifies the persisted generation, expiration, active job, current policy, company/project/lead/conversation and authentic synthetic inbound marker. Absent task capability preserves the original closed readiness behavior.

The worker locks the grant and published settings row for the bounded execution. The SDK independently checks the current grant and the reserved AgentRun ID against its exact pin. The provider adapter checks the current job and synthetic destination before returning a deterministic fake receipt. The grant lock serializes operator revocation with active work; it is not instantaneous model cancellation. The revoked negative case is queued, then revoked before claim. The router must put it in review with no inference, no provider and no legacy fallback.

Three staging-only tables record the grant and independent invocation/send evidence. The original job, AgentRun, outbound, message and Hermes state tables carry the real operational records. Unique invocation and send rows reject a second attempt. An uncertain failure is not automatically replayed by this harness. The only intentional requeue is the first already-completed fixture, after verifying its durable receipt, to test idempotence.

## 4. Network and effect controls

Only hosted GitHub Actions under `RUNNER_TEMP`, using a local Docker context. The pre-existing persistent foundation workflow builds the normal API, frontend, SDK and PostgreSQL. The dedicated worker uses the existing API image and internal network. It receives no real model or provider credentials. The temporary SDK container uses the existing SDK image, no published ports, UID/GID 10001. In model mode only, a temporary egress network is attached exclusively to that container; it is general egress, not a destination allowlist. The dedicated OpenRouter key is supplied only to the SDK, not committed to disk in a Compose configuration or printed. No actual Telnyx or Google Calendar credentials are provided. The fake transport is the only accepted SMS destination and WhatsApp is denied. Native effect execution functions are explicitly denied in the test process. The ordinary API and private SDK gate are restored after the test. Hosted CI cleans containers, volumes and networks.

## 5. Acceptance sequence

1. Run existing foundation and guard tests; build and verify the normal closed topology; recreate without deleting PostgreSQL.
2. Stop original frontend/API/SDK to avoid queue competition. Seed the separate synthetic live fixture and grant. Start the dedicated private SDK.
3. Enqueue first fixed message through the original tables and continuity receipt. Verify duplicate enqueue returns same job. Claim with the actual worker. Verify private HTTP missing/wrong auth (401), unknown/unreserved job/run (409), extra prompt (422), no public schema (404). Run original router, private SDK and dispatcher. Require one runtime invocation, one simulated provider send, one accepted message and revision 1. Check Van Buren and the verified 3 bedrooms fact.
4. Restart the temporary SDK. Intentionally requeue the already-completed original event. Require identical AgentRun, reply, policy, revision, invocation and send counts. No additional inference/send.
5. Enqueue second fixed message. Require a distinct AgentRun, original published policy, second accepted receipt and state revision 2. Check Van Buren and the verified 1 bathroom fact.
6. Enqueue the third fixed message, revoke grant, run actual claim and router. Require review (`HERMES_NOT_READY`), zero invocation/send for the denied event.
7. Verify two completed runs, two accepted simulated outbound messages, two invocation markers, two fake send markers, three job rows (including the denied job), two state revisions, no Meeting/CalendarConnection/HermesSalesOperation/SalesAssetShare/SalesFollowUpJob rows, no pending/retry/processing jobs. Restore the normal closed services; authenticate via real staging API and inspect revision 2; deny cross-scope inspector request; verify global selector remains LangGraph and Hermes readiness false.

The model lane runs the same sequence with real inference; offline substitutes deterministic answers. A runtime invocation is a whole turn, not necessarily one underlying model API request. The natural-language fact checks accept digits or words; they are not comprehensive semantic evaluation or a replacement for the certified 18-scenario suite.

## 6. Upload Ready and GitHub Actions

Only six files: `live_scope_policy.py`, `live_scope_runtime.py`, `live_scope_acceptance.py`, `test_live_scope_policy.py`, this document, and the updated canonical `.github/workflows/hermes-hei06a2-persistent-staging.yml`.

Upload the ZIP contents with their full relative paths. The canonical workflow replaces the existing file, never create a second YAML. Commit:

`test(hermes): certify scoped live inbound worker with private SDK and simulated receipts`

Check automatic `Hermes HEI-06 isolated evaluation` and any ordinary deploy triggered. This change may not trigger production deploy because it only changes staging files.

Open `Hermes HEI-06A.2 persistent staging foundation` → Run workflow → branch `main`.

- Offline: `run_live_worker=true`, `run_openrouter=false`, `run_scoped=false`.
- After offline PASS: `run_live_worker=true`, `run_openrouter=true`, `run_scoped=false`.

The simulation lane is already certified on base; `run_scoped` may still be selected for a combined regression, but is not required for this new acceptance. Existing `HEI06_OPENROUTER_API_KEY` is reused. No new secret, server command or production deployment required.

Artifacts: `initial.json`, `recreated.json`, optional `scoped.json`, `live-worker.json`, `summary.json`, and sanitized startup diagnostics on failure. The new report distinguishes `one_shot_live_worker`, `real_inference`, `continuous_api_worker_authorization`, `real_provider_acceptance`, `production_readiness`. In case of failure share `live-worker.json` rather than raw model logs. No real customer data, raw conversation, keys, SQL or exception messages are intentionally exported. Do not advance to provider acceptance until the new test passes and the normal staging worker authorization is reviewed.

## 7. Local validation and known limitations

65 local unit tests passed (41 from the preceding staging packages, 24 new policy/context tests), on an assembled copy of those staging files. Python syntax, canonical YAML parsing, Bash syntax and ZIP integrity checked. No Docker daemon or complete private application checkout is available locally, so real PostgreSQL, actual claim/receipt transactions, container DNS, model inference and browser/HTTP integration are **not** claimed as passed. GitHub Actions is the first complete run of this new lane. Actual continuous API worker scheduling is deliberately out of scope; real provider acceptance remains pending. No remote changes or commands on DigitalOcean were made.
