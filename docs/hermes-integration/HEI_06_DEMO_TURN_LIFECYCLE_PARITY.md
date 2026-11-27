# HEI-06 — Demo Turn Lifecycle Parity

**Base:** `ea0e96f1502e36ef2d11019c9cfa63ea2a43a72a` (BlackPenguin).
**Reference:** `jorgektch/testing-hermes-agent@9ac4c8703d28eb3ca39fc762df0dd67c7196e324` (v13.3.3).
**Prior run:** https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45950137879

## Evidence and scope

The prior deployment succeeded; controlled model acceptance was 9/18: focus-media, ordinal and comparison 3/3 each; no-match, temporary and visit 0/3 each. All original offline checks passed. Two visit variants reached `visit_times`; their SDK attempted `select_visit_time` rather than reading availability for the chosen day. The first variant stopped at `visit_days`. All no-match and primary-preference failures reached `prepare_returned`, so the prior redacted report cannot establish the precise failed assertion or committed value. The new code addresses verified structural defects and adds explicit evidence to localize any remaining failure. No claim of a new model pass is made.

### Verified defects

1. `choice_state.record_delivered_menu()` delegated to `contextual_choices.menu_record()`, which discarded `display_name`. The live renderer had already established that name, and `visible_menu()` used it in the delivered text. On the next turn, the persisted menu could fail the proof because it no longer contained the commercial label; the internal property ID may not be visible to the buyer. Preserve the approved label alongside the unchanged internal ID and accepted outbound receipt.
2. `commercial_delivery.search_reply()` repaired zero matches only if the monetary guard rejected the text. A valid zero-match domain result needs to be communicated even if the SDK's answer contains no money. Repair missing/incorrect unambiguous two-filter queries through the existing search tool; do not widen unverified results to alternatives.
3. The previous normalization required a prior preference revision. An initial explicit exploration can have no stored primary profile. Support it without changing primary preferences. Use the existing exclusive price filter for strict `under/below/less than`, and retain the max-price field for the displayed cap.
4. `commercial_turn.intent()` can classify the word 'options' in a day availability request as a property search. The delivery policy must use the actual visit request and scoped slot result, not that generic hint alone.
5. Typed visit selection recovery used to wait until after SDK inference. A rejected incorrect SDK tool call could then prevent the repair. Prepare a fresh, delivered, unequivocal typed visit selection before inference, as the demo does; identical SDK requests reuse that result, incompatible calls are rejected without changing the authorized draft. A day selection is a read; a time selection is only a recap draft.
6. The previous capture already attempted explicit preferences before the model. It was not possible to establish from the redacted report why all three primary assertions failed. Verify the native capture against the existing pure preference application, compare its snapshot before/after inference, and record the actual outcome. Never replace it with model-generated state or silently report a successful capture without proof.

## Responsibility map

| Demo component | BlackPenguin adaptation |
|---|---|
| `domain.begin_turn()`, `domain.verify_explicit_preferences()` | Native `update_search_preferences` draft; check exact revision and evidence, inject verified context. |
| `contextual_choices.py`, `v1333_contextual_choices.py` | Persist typed menu label and receipt; resolve day/time using already delivered menu and proposal; prepare native read/selection before SDK. |
| `delivery_policy._no_matches_for_state()` and `validate_outbound()` | Repair only explicit supported criteria from native search; no-match delivery independent of monetary rejection; reuse monetary guard. |
| `hermes_runtime.py` | Unchanged SDK and one invocation of its existing agentic loop. |
| `domain.end_turn()` / persistence | Unchanged live receipts and CAS state persistence; only accepted text makes a menu/recap actionable. |

No new LLM, no LangGraph orchestration, no general secondary intent classifier. The narrow complete two-filter request contract limits deterministic read recovery to requests whose qualifiers can be accounted for. Other requests remain Hermes-led. The full tenant, scope, enabled tool and readiness checks remain. The actual effect executor, provider transport, production gate, SDK revision, model, prompts, migrations and environment settings are unchanged.

## Turn flow

1. Authenticate, verify scope/epoch/policy and invalidate stale evidence (existing path).
2. Capture an explicit permanent self-declaration via native draft, if enabled. Check against the existing pure preference implementation. Resolve an unambiguous delivered visit choice only with matching property, proposal, receipt, option membership and expiration. A native read/selection is recorded as such. No booking at this step.
3. Run Hermes with updated verified context. If it repeats a prepared visit selection, reuse the result; if it asks for another day/time in that same resolved turn, reject that draft request. Do not promote rejection to authorization. Hard denials are not recoverable.
4. If an explicit simple catalog query has no exact completed search, recover one native read (only if the authorized tool is enabled and observed tools permit it). Present zero results or a verified single result when necessary; retain existing multi-result/menu logic. The original monetary guard is still applied; ephemeral buyer-budget evidence is only used for canonical responses. No fabricated catalog prices.
5. Render and prepare a scoped draft; existing immutable provider receipt and native-effect boundaries remain responsible for actual persistence and execution. Confirmed booking still requires a separate affirmative inbound and the existing booking tool and executor.

## Files

Production code (existing):
- `backend/app/modules/hermes_sales_core/choice_state.py`
- `backend/app/modules/hermes_sales_core/commercial_delivery.py`
- `backend/app/modules/hermes_sales_core/live_preparation.py`

Evaluation (new):
- `services/hermes_worker/evaluation/test_turn_lifecycle.py`
- `services/hermes_worker/evaluation/test_turn_lifecycle_harness.py`
- `services/hermes_worker/evaluation/lifecycle_evidence.py`
- `services/hermes_worker/evaluation/test_lifecycle_evidence.py`

Evaluation (existing):
- `services/hermes_worker/evaluation/test_staging_conversations.py`
- `services/hermes_worker/evaluation/run_staging.py`
- `.github/workflows/hermes-hei06-controlled-staging.yml`

This document is included under `docs/hermes-integration/`.

## Tests and diagnostic evidence

- Local isolated: 22 existing focused checks + 23 new lifecycle checks + 3 safe evidence checks = **48/48**. The prior local harness uses exact retrieved pure preference/parser/money modules and operation receipt module, plus small doubles for dependencies of the complete private application; no full ORM, Docker or OpenRouter was run locally.
- New integration: 9 cases over the actual isolated ORM/private HTTP/provider-double lane; reuse `staging_scenarios.exercise` for the three previously failing families. They intentionally omit or misuse SDK tools, supply stale filters and misleading response text. Pending CI execution.
- Original 22 offline transport/harness scenarios, 9 exporter checks, and 18 paid model cases remain unchanged. The paid lane still depends on the entire offline job passing. Original acceptance assertions and variants in `staging_scenarios.py` are unchanged.
- Python syntax and YAML structure checked locally; base blobs for all modified existing files verified against the candidate commit.
- `model.json` adds `lifecycle` alongside original trace. `before_sdk`, `after_sdk`, `prepared`, `persisted`, `outbound`, `sdk_tool`, `domain_tool`, `failure` records contain allowlisted fixture-specific boolean/count/enum fields and failure source locations. `failure_line` / `failure_column` (when available) locate the static acceptance assertion without exporting exception messages. `failure_reason` maps known preparation errors. No raw reply, prompts, tool arguments, IDs, URLs or secrets. If evidence is truncated/missing it is labeled, not guessed.

## Upload

1. Extract the Upload Ready ZIP and upload its directory contents, preserving paths, to https://github.com/BlackPenguinAI/BlackPenguin/upload/main . No apply scripts, build step, migrations or configuration changes are required before upload.
2. If the hidden `.github` directory is skipped by the web UI, replace `.github/workflows/hermes-hei06-controlled-staging.yml` separately with the supplied YAML.
3. Suggested commit: `fix(hermes): align verified turn lifecycle with demo`.
4. Wait for the normal deployment workflow to succeed (check its status yourself). Then manually run `Hermes HEI-06 controlled staging acceptance`, branch `main`, input `run_openrouter=true`. The new 9 integration cases must pass before OpenRouter is used. Do not enable Hermes for production traffic.
5. If the offline job fails, inspect the specific failing integration step. If the paid job fails, download its artifact `hei06-controlled-model-<commit>` and share `model.json`; the additional safe lifecycle fields distinguish capture, preparation, persisted state and actual delivered reply. The full deploy regression and real SDK evaluation are not yet certified for this patch.

## Remaining limitations

The three preference failures and three no-match failures in the previous run were not fully localized to an exact assertion by its old trace. The intervention resolves identified design gaps; whether it resolves every failing scenario is determined by CI, not by local double results. The typed preflight is deliberately limited to fresh delivered multi-option menus; single-slot receipts, complex/mixed requests, multilingual/currency expansion beyond the existing USD preference contract, and real provider acceptance remain outside this iteration. Booking confirmation/effects are unchanged; the previous model run never reached the final booking checkpoint, so new downstream failures may surface. Production readiness remains CLOSED. No GitHub writes or deployment actions were performed by the assistant.
