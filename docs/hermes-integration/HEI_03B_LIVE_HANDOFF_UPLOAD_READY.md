# HEI-03B.2 — Live Turn & Delivery Handoff (guarded candidate)

## Scope and baseline

- BlackPenguin main: `2f5695d6a038efd1bc13df812dc0d2d1269dacc2`.
- Previous deployment: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45768745848 (success at audit time).
- Existing files checked against GitHub blob SHA before editing:
  - `backend/app/modules/sales_agent/engine_router.py`: `21d469ef5d1fa5aa5e40f994848836c2bfceb08d`.
  - `services/hermes_worker/sdk_smoke.py`: `a9ef5dff443377eafb72d4791fdf5e4e1ec3e636`.
- `production_tools.py` from HEI-03B retained unchanged (`564300f6b82253300daf0d8ea664eaee922dc2cd`).
- No DB schema changes, migrations, NoSQL changes, onboarding edits, provider configuration changes or deployment modifications.
- **Do not activate Hermes in production.** `live_hermes_ready()` remains false. Existing worker invocation does not supply a certified Hermes handler. This is a candidate integration boundary, not a working production lane. LangGraph remains the selected/default effective engine until the explicitly certified cutover.

## Upload

Extract ZIP and upload files relative to the repository root; no scripts, patches or manual migrations. Commit:

```
feat(hermes): add guarded live turn and material delivery handoff
```

The independent `.github/workflows/hermes-sdk-smoke.yml` was not present in the audited commit (404); upload it separately at `.github/workflows/` if the browser omits hidden folders. The standard deploy workflow is not modified. The SDK smoke builds the pinned SDK and checks imports offline; it does not certify provider or model integration.

## What this release does

| Component | Responsibility |
|---|---|
| `live_preparation.py` | Scope, active opportunity, real channel, current inbound, reserved AgentRun, immutable policy pin; prepares with the real Hermes SDK and existing parity tools, without committing business writes. Channel-specific material verification, approved visit location, existing formatting and monetary/language checks. |
| `live_coordinator.py` | Stable draft envelope, bounded state and safe observations, digest verification, reconstruction without calling the LLM, stable provisional delivery key, reconciliation and orchestration of CRM/booking/material adapters after accepted reply. |
| `live_receipts.py` | Exact provider/outbox/message/run binding, continuity epoch, single-part receipt, actual displayed choices, full visit recap including location/timezone, existing state CAS, AgentRun receipt. |
| `live_materials.py` | Issue exact approved batch using existing `asset_share_service.issue`; bind each share to its run and channel, keep raw bearer URLs out of Hermes operation records; reconcile complete accepted delivery group and consume the request with state CAS. |
| `engine_router.py` | Optional explicit Hermes inbound handler (no default). Still fails closed if readiness is false, handler is missing, or job is a follow-up. Legacy route unchanged. |
| `sdk_smoke.py` | Import checks for candidate modules; verify gate remains false. |

## Intended transaction boundaries (future certified worker)

1. Existing worker claims event; `route_live_job(..., hermes_handler=...)` writes immutable event pin and commits before invoking the handler. A gate alone must never install a handler.
2. Handler validates real lead authorization and shared deterministic controls, reserves `AgentRun` using `reserve_live_run`, commits the reservation.
3. `prepare_live_turn` builds a draft from published configuration and scoped real data. `persist_live_draft` saves it before dispatch, with no tool argument/history/secret trace. Commit. A replay reconstructs via `restore_draft`, not a fresh model request.
4. `provisional_delivery_plan` supplies stable key `hermes:reply:<run_id>`. A certified shared provider dispatcher must persist exact accepted single-part message/outbox rows with its metadata. It must reconcile any earlier uncertain or queued attempt rather than send again.
5. `reconcile_live_reply` verifies persisted draft, actual accepted `SalesMessage`, exact `OutboundMessage`, matching run, opportunity, continuity epoch, expected revision, and exact reply text. Commit accepted dialogue/state separately from effects.
6. `advance_live_effects` invokes HEI-03B's existing CRM preferences, first appointment, or materials adapters. Booking must leave the existing Calendar operation pending until synchronized. The returned material plan contains sensitive bearer URLs; only a trusted internal delivery caller may consume it. Never print it or copy it into diagnostic output.
7. Material issuance uses one `HermesSalesOperation` per request, status `pending_delivery`. The dispatcher must bind its original share IDs and full approved bindings to the existing outbox parts, preserving `run.output_snapshot.reply` as the original provisional reply. A crash/unknown provider outcome requires reconciliation of the original group; do not remint tokens. `complete_live_material_batch` records accepted/delivered status only after verifying every part/share; no new provider call. Caller commits.
8. Only after accepted final receipts may the worker mark the event handled and close the existing inbound job. A real appointment confirmation must derive from the persisted Meeting/BookingOperation, never LLM prose or a simulated receipt.

This release implements steps 2–3 and receipt/effect adapters for 5–7 plus the explicit router seam in step 1. Steps 4, final delivery and job completion in 7–8 are **not wired** to the currently deployed worker. The production lane must stay disabled.

## Open release gates / limitations

- The SDK Docker image is still isolated and not deployed as the existing production worker. The candidate requires `OPENROUTER_API_KEY` and pinned SDK at runtime, but do not add environment variables to production yet.
- The current `live_service._dispatch_part` calls `active_service.authorize_part` only for `sales-active/1.0`. Do not label Hermes as that engine to gain authorization. Add a native pre-provider authorization hook for Hermes, including scope, consent, epoch, current tool/policy and exact material snapshot checks. The standard dispatcher also updates `run.output_snapshot.reply` on each dispatch; a follow-up material/booking receipt must preserve the provisional reply evidence in HEI-03B. Use a dedicated explicit send/receipt path with existing outbox/provider services, not a duplicate provider stack.
- No concrete live job handler is installed. Need shared deterministic STOP, consent withdrawal, moderation, handoff, pause/resume, cadence/inactivity, and job completion paths before enabling. `live_preparation` rejects control messages rather than processing them via a model. Do not claim that rejecting STOP is adequate opt-out handling.
- Preparation presently requires the latest authenticated inbound and holds a DB transaction during synchronous inference. Need a bounded, isolated SDK execution strategy and validation of rapid successive lead messages with PostgreSQL concurrency. No change to the queue schema.
- Provisional replies must be exactly one accepted part. No multi-part conversational receipt support yet. Provider statuses `queued`, `sending`, `delivery_unknown` do not authorize native effects; handle async provider reconciliation. Do not retry blindly.
- Exact location/timezone and property reference must be visible in recap; current offer validator requires exact reference and time. One-slot offers, natural-language date selection, media assent and richer profile updates need real dialogue testing. Material batch supports local approved files as in HEI-03B; external gallery URLs still need a validated binding. Cancellation/rescheduling live effects are not implemented.
- Candidate draft includes scoped commercial state in the existing `AgentRun.output_snapshot`; this is not a second database. It must remain internal, not exposed through inspector diagnostics. No raw share bearer URLs in the Hermes operation receipt. Existing actual outbound customer message necessarily contains its access URL.
- The proposed production route is not certified by these tests. No actual SDK invocation/OpenRouter/Telnyx/Google Calendar/production PostgreSQL operation was executed. No repo or server mutation made by assistant. Full CI and controlled non-production tests are required.

## Validation

Local isolated test root re-used previous HEI test modules and extracted code; SQLite ORM stand-ins and mocked business services, not a full repo checkout. Test command: `python -m pytest -q tests --disable-warnings` (isolated subset). Result: **203 passed, 22 warnings in 8.24s**; 53 new tests and 150 previously delivered tests rerun. Warnings are not considered provider certification. Full BlackPenguin CI is still pending for this commit.

Coverage: stable engine pin and explicit router handler, hard gate even if handler supplied, no fallback, rejection of unsupported follow-ups, exact scope and provider key/epoch binding, single-part restriction, hidden menu exclusion, full recap, stable draft digest, tamper rejection, asset URL validation, batch issuance, no token in operation ledger, no remint, binding order and CRM-before-booking ordering. Tests of the new coordinator exercise deterministic helpers and service doubles, not the real runtime or a real provider.

## Next concrete work

Close HEI-03B with the actual authorized shared dispatcher/worker integration and real controlled test of an inbound conversation, document sharing, confirmed booking, asynchronous provider status and Calendar receipt. Then move to HEI-04 Conversation Inspector. The switch remains disabled for live Hermes until the HEI-06 acceptance and HEI-07 cutover. The existing LangGraph configuration and other BlackPenguin modules remain untouched.
