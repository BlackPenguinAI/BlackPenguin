# HEI-06 — Commercial Delivery Parity

## Candidate and scope

Base BlackPenguin commit: `5237dc50c29c29260163cad56c33c78aa0ab2819`.
Reference demo: `jorgektch/testing-hermes-agent` at `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`.
Observed evaluation: [controlled staging acceptance #1](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45945306064), 8/18 passed, 10 failed. Private network/offline lane passed. All three focus/material and all three property ordinal scenarios passed. Comparison 2/3; no-match, preference and visit families 0/3. Six failures stopped at the monetary guard; three at the first visit-day checkpoint; the remaining comparison trace did not expose enough reply text to distinguish a semantic error from an assertion-format issue.

This is a candidate for the next acceptance run, not production activation. The real SDK, tool registry, engine selector, production gate, native booking/Calendar/Telnyx executors, existing tests and database schemas are not changed. No external actions, repository writes or deployments were performed when preparing this package.

## Responsibility parity with the demo

| Demo component | BlackPenguin adaptation | Responsibility |
|---|---|---|
| `hermes_runtime.py` / `AIAgent.run_conversation` | Existing runtime, unchanged | Hermes interprets the buyer, chooses tools, handles dialogue; no second model or graph. |
| `domain.verify_explicit_preferences`, `sales_preferences.py`, `commercial_turn.py` | Existing preference draft tool; capture clear current declarations when that tool is enabled | Domain validates source evidence, revisions and idempotence. No pre-inference mutation of the CRM or provider effects. |
| `search_sessions.py`, `domain.search_properties` | `reconcile_temporary_filters` in the live search adapter | The existing explicit filter parser prevents an exploratory USD ceiling from being silently clamped to the saved primary budget. Only simple bedroom/cap reads are covered, not generic natural language routing. |
| `delivery_policy._no_matches_for_state`, `_matching_reply` | `commercial_delivery.search_reply` and `verified_budget_profile` | When the existing monetary guard rejects a reply, use a complete current-turn exact search result to render zero or one match. The existing numbered-catalog repair still owns multi-property menus. No invented alternatives, no new price source. |
| `domain.compare_properties` | Explicit named comparison context and scoped reads; `compare_reply` | Distinct named properties may be read without selecting a single focus. An explicit simple count comparison can be rendered from actual comparison or two detail results. Compound topics stay on the normal path. |
| `v1333_contextual_choices.py`, `contextual_choices.py`, `delivery_policy._pending_visit_recap` | Turn-local successful slot ledger, canonical typed menus, exact recap | Presentation and explicit ordinal selection belong to the domain. Keep the actual property, calendar timezone and proposal. A recovery is limited to an authorized availability read or selection draft, never a booking. |
| `persistence.py` and `domain.end_turn` | Existing immutable draft, receipt verification, optimistic state revision and native effect coordinator | BlackPenguin commits only after actual accepted delivery and existing scope checks. A proposal is not a reservation. |

The new module is not a general intent classifier. It is a bounded delivery/verification adapter. Existing domain parsers, approved catalog, calendar reads, tool authorization and output guards are reused. The ordinary SDK reply remains the default outside these narrowly identified contracts. Unlike the demo, the production integration must preserve authenticated receipt, tenant, policy and idempotence checks. The exact `display_name` for a visit is derived from the scoped catalog and must be unique, not supplied by Hermes. Internal references remain in state and effect identity. Legacy receipts without a display label retain the original reference check.

## Changes and safety details

- Primary preferences are drafted only from clear declarations, using the existing enabled `update_search_preferences` tool. Repetition of the same declaration does not increment the revision again. Exploratory requests do not revise the primary profile. This capture is a domain operation, not a fabricated Hermes-originated tool observation.
- Temporary USD search filters are reconciled only on an actual selected search tool with supported filter keys and an existing primary profile. Other tool arguments/requests stay on the ordinary path. Current existing parser is English/USD-oriented; no general multi-currency or language support is certified here.
- The original `validate_monetary_reply` implementation remains unmodified. The budget evidence is a transient profile projection, used only on server-generated canonical repairs, not the original model prose. It does not create a catalog price, change the persisted profile, or allow a budget amount to be quoted as a property price. A second pass through the existing guard is mandatory. The no-match response says *no verified matches*, not a claim of exhaustive market inventory. Optional alternatives and complex/range comparisons are not repaired by this candidate.
- Comparison does not allow arbitrary foreign references or promote failed reads to facts. Count rendering is restricted to two distinctly named records and successfully read values. No evaluator regex is relaxed.
- The slot ledger is scoped to the current turn and retains the actual successful proposal; a later speculative narrower result is not allowed to replace the exact menu being displayed. A general day query may recover one authorized broad read if needed; an explicit ordinal may recover a read or selection draft. The recap includes approved property name, exact ISO date, 24-hour clock, project timezone and visit address; it is explicitly not booked. Existing confirmation/effect checks are untouched. One-slot receipt handling is deliberately unchanged; this candidate addresses the multi-option flow exercised by the failing scenarios. The confirmation and final booking stages still require integrated evidence and may reveal additional issues.
- The new workflow step executes 22 focused tests before the existing 31 offline and 18 real-model acceptance cases. The original scenario/assertion suite, test model, secrets and provider boundaries are unchanged.

## Verification actually performed

Reconstructed the three replaced files from the exact GitHub connector content and verified their baseline Git blob hashes:

- `live_preparation.py`: `7e2f4318a5f27f0fd7d285008c9a2fc93d6f1101`
- `bp_operation_receipts.py`: `a7f61ab568a3fc42535d17effde2d52039af2877`
- `.github/workflows/hermes-hei06-controlled-staging.yml`: `c66abba10e6e1c5930782161f799c5c7280a74d4`

Local focused harness: 22/22 passed. It used the new delivery/receipt modules, reconstructed baseline `commercial_turn`, `sales_preferences` and `money` files with matching Git blob SHA; baseline monetary validator source and relevant menu/display helpers, with a double for the port and date parser. This was **not** a full repository clone, ORM integration, full test suite, Docker/SDK execution or real OpenRouter test. The local environment had no GitHub network access. The test file is included and CI will exercise it with the actual repository modules rather than the local helper copies. The local helper copies are not part of the upload. Python syntax and YAML structure checked; no secrets, generated caches or local fixtures in this ZIP.

The 8/18 passing baseline cases are expected regressions to preserve, not a claim of rerun success. The new candidate remains unverified at integrated level until the GitHub Actions artifacts are available.

## Upload and acceptance

1. Confirm the repository still has the baseline commit or inspect differences if it has advanced. Extract the ZIP into the repository root, preserving paths. Upload only its six files (three modified backend files including one new module, one new evaluation test, one workflow, one document). No patch script is needed.
2. Ensure `.github/workflows/hermes-hei06-controlled-staging.yml` was actually replaced, since browser uploads may omit hidden directories. The standalone YAML is available separately.
3. Commit: `fix(hermes): align commercial delivery with demo domain evidence`.
4. Wait for the ordinary deployment to finish. Execute **Hermes HEI-06 controlled staging acceptance** on the new main commit. First run without `run_openrouter` if you want to check offline without spending model credit; then run with `run_openrouter=true`. It automatically runs offline tests before paid cases. Reuses `HEI06_OPENROUTER_API_KEY`.
5. Preserve the actual offline/model artifacts and run URL. Do not retry until green without analysis. Target 22 focused, 31 existing offline and 18 real-model scenarios, with no skipped/duplicate cases and zero unauthorized effects. If a failure remains, inspect the exact failed checkpoint, tool status and scoped result rather than relaxing the assertions.
6. Keep production gate CLOSED, LangGraph selection unchanged and HEI-07 blocked. Real Telnyx/Calendar, active isolated cross-container transport, actual intended published policy, operator scope and rollback rehearsal still require separate authorized staging evidence.
