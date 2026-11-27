# HEI-06 — Demo-aligned catalog responsibility boundary

Base: `5b8e40f992a2d65b0eda01b853996558aab92e1a` (BlackPenguin main, checked through GitHub). Evaluation #14: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45936319193 . Demo reference: `jorgektch/testing-hermes-agent` at `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`.

## Evidence and limits

The supplied sanitized report has 3/4 real-model cases passing. Both named-focus/PDF cases complete, as does numbered-choice repeat-1. Repeat-2 has an executed `search_properties`, then a rejected `search_properties` whose original error code was collapsed to `unknown_error`; the model returns two numbered lines, but the delivery gate rejects monetary reconciliation with `request_or_tool_evidence`. The exact arguments, price and original rejection code are not captured. The source proves that both repair paths rejected all failed tool observations and that `ParityOperationalPort._search` cleared `search_rows` on a failed call. Known argument-validation errors from the authorized read port include `INVALID_SEARCH` and `PERMANENT_SCOPE_REQUIRES_EVIDENCE`. These are reproducible cases, not a claim that either was conclusively the hidden error in run #14.

## Reference architecture, not a new commercial agent

| Responsibility | Demo source | BlackPenguin target / this change |
|---|---|---|
| Interpret current goal, choose tools, explain results naturally | `backend/app/hermes_runtime.py`, real `AIAgent` | Same SDK/runtime; no alternate LLM or LangGraph fallback. |
| Return filtered, trusted catalog results | `domain.py`, `search_sessions.py`, search tool handlers | Existing scoped read port. No new catalog query, writes or privileges in the renderer. |
| Preserve successful facts when a later exploratory call fails | `hermes_runtime.py` (successful `_matching_options_this_turn`, rejection cache and next action) | Turn-local successful search ledger. Recoverable rejected reads are not promoted to successes. |
| Deliver valid prices/numbered menu, independent of raw model formatting | `delivery_policy.validate_outbound`, `property_options.render_matches` | Shared catalog-read evidence contract; exact-request and visible-menu rendering from actual successful rows, with unchanged monetary/language checks. |
| Resolve visible ordinal on the next turn | `v1333_contextual_choices.py`, `property_options.delivered_snapshot` | Existing receipt-backed typed choice ledger; commit only after accepted provider receipt. |
| Preferences, assets, booking and provider effects | Domain, consent, persistence and delivery policy | Existing native gateway, permissions, scope, receipts and transaction/idempotency checks; no change here. |

Demo references:
- https://github.com/jorgektch/testing-hermes-agent/blob/9ac4c87/backend/app/hermes_runtime.py#L350-L414
- https://github.com/jorgektch/testing-hermes-agent/blob/9ac4c87/backend/app/delivery_policy.py#L278-L370
- https://github.com/jorgektch/testing-hermes-agent/blob/9ac4c87/backend/app/property_options.py#L128-L181
- https://github.com/jorgektch/testing-hermes-agent/blob/9ac4c87/backend/app/v1333_contextual_choices.py#L216-L326

The demo itself uses deterministic response rendering, read-result recovery and typed selection; it is not an unconstrained LLM. Preserve its division of responsibilities, not its synthetic database, direct media URLs or simulated booking receipts. This package addresses the catalog slice, not an exhaustive claim of parity for the entire commercial lifecycle.

## Implementation

- `catalog_read_evidence` distinguishes accepted read evidence from rejected input validation. Only `INVALID_SEARCH`, `PERMANENT_SCOPE_REQUIRES_EVIDENCE`, and SDK argument-shape `TOOL_ARGUMENT_INVALID` on `search_properties` are recoverable, and only if a successful search exists. A rejected read contributes zero rows. Explicit permission, disabled tool, commercial hold, unknown errors, noncatalog tools and mixed effects cannot authorize these repairs. `get_project_overview` must be an executed successful read. The number of successful search observations, not total attempted searches, must match the actual ledger.
- Live port retains its most recent successful search rows when a later known invalid search returns a validation error and active-search state still matches the ledger. It supplies a safe next action to reuse verified results; no new inference, no retry, no fabricated tool observation, no preference revision. The invalid call remains rejected. Successful later searches (including zero results) still supersede the previous result normally.
- Direct exact-query presentation continues to select one complete matching batch, including an earlier exact batch; the existing strict simple-request grammar and inventory checks remain in force. General visible-menu recovery uses the most recent actual successful batch and the normalized delivered subset/order, independently of a transient proposed menu being absent. It requires verified inventory, current source, ledger consistency, buyer filter and existing visible-menu proof. No union of different searches, guessed rows, synthesized receipt or cross-turn recovery. If the model reply is accepted as-is outside these cases, its normal path remains unchanged. Mixed requests, unresolved evidence and authorization errors remain outside recovery.
- Tool schema explains the boundary: search is a read, temporary by default; durable preferences require a separate authorized tool and explicit declaration. It advises using successful results and full explicit-currency prices. No published policy version, model, engine selection, dependency or prompt registry changed.
- Diagnostics retain the two fixed search-validation codes instead of masking them, and record final visible-menu reconciliation as well as exact-query reconstruction. Never export raw model output, arguments, prices, private URLs or secrets. The four opt-in live scenario assertions are unchanged; only their observation wrapper is expanded.

## Validation

Original modified files were checked against the candidate GitHub blob hashes (including the real SDK test fixture). The twelve previous HEI suites also matched their GitHub blobs. Used the existing isolated Python 3.12 image environment, real ORM/worker/dispatcher and SQLite, with SDK/provider doubles in the offline harness. The latest offline harness reproduces (a) multiple successful searches followed by an invalid filter, then actual numbered selection, and (b) a natural search without the explicit numbered-list phrase, followed by a rejected permanent-scope read; it proves primary preferences remain unchanged, the menu is accepted, the selected property's fact is correct, and STOP remains inference-free.

- 203 tests in HEI-01A to HEI-03B.2 passed.
- 115 tests in HEI-03B.3 to HEI-05 passed.
- 131 tests in numbered price reconciliation (89), focused fact grounding (32), diagnostics (9), and offline worker harness (1) passed.
- Total: 449 unique local test cases passed (29 more than 420 in the preceding delivery). No failures in those invocations. Python syntax of the expanded real SDK fixture checked; paid-model scenarios were not executed locally. Full repository CI, real-model evaluation and new candidate PostgreSQL lane still need verification. Real Telnyx/Calendar and private network service/actual published policy/rollout/rollback acceptance remain outstanding.

## Upload and reevaluation

Upload these complete repo-relative files through GitHub Upload Files. No patch, migration, new secret, or workflow configuration change. Commit: `fix(hermes): align catalog delivery with demo read-evidence boundaries`. Run a NEW HEI-06 workflow_dispatch on the new main SHA with `run_openrouter` enabled. Do not keep re-running old SHA/inputs to cherry-pick a pass. Retain readiness CLOSED. Even 4/4 in the small real-model suite does not by itself certify production: use results as a limited regression check, then evaluate a broader conversation matrix and controlled external services before cutover. If another failure occurs, inspect the sanitized actual rejection code and both rendering paths; do not widen policy or rewrite commercial logic just to turn CI green.
