# HEI-06 — Delivery Boundary & Search Autonomy Hotfix

**Base BlackPenguin:** `b4d2e57ee5e82260a346b0038f91aaccf9aea332`  
**Reference demo:** `jorgektch/testing-hermes-agent`, `9ac4c8703d28eb3ca39fc762df0dd67c7196e324` (v13.3.3 architecture).  
**Status:** candidate, not certified; production readiness CLOSED.

## 1. Observed regressions

Deployment #477 succeeded. Controlled Staging Acceptance #3: 19/22 offline, with the three `no-match` cases failed; paid OpenRouter lane skipped. Isolated Evaluation #19: 32/33 in `offline_harness`; later PostgreSQL and model checks were not reached. All 48 focused tests passed in the previous candidate. The previous reports omit the individual assertion traceback, so exact root cause per failed case remains unconfirmed until CI. The following code defects are deterministic and consistent with those failures.

- The prepared canonical no-match response quoted an explicit USD ceiling and used an ephemeral preference profile to pass the monetary guard. The shared dispatcher validates against the persisted Lead profile and rejects if content changes. New permanent declarations also are persisted only after accepted delivery. Preparation-only exceptions therefore cannot guarantee a valid send.
- `_live_port._search` normalized every eligible search against the current buyer message, overwriting a distinct narrower query selected by Hermes. The original offline harness explicitly tests independent searches at USD 350,000 and USD 330,000 and expects two and one returned homes, respectively.

## 2. Implementation

### Delivery boundary

`commercial_delivery.py` canonical no-match response now refers to the stated budget instead of echoing an unpersisted monetary amount. Example: “I found no verified matches for homes with 6 bedrooms within your stated budget. Would you like to adjust your budget or the number of bedrooms?” The exact cap, requested bedrooms and source inbound remain in the verified active search; the primary preferences remain unchanged. A new primary-preference acknowledgment likewise refers to the stated budget without repeating its amount. Verified listing prices still use the approved catalog.

`live_preparation.py` no longer constructs a preparation-only budget profile. Both monetary validation boundaries use the actual persisted profile; the dispatch backstop remains unchanged. An invented listing price still fails. This is a narrow solution, not a general mechanism to echo an arbitrary unpersisted budget. The latter would require a future explicitly authorized, end-to-end evidence contract.

### Search autonomy

`_live_port._search` no longer rewrites independent agent criteria via `reconcile_temporary_filters`. Exact matching requests retain the existing strict-price bound (`relative_price_lt`) where applicable. The existing `ensure_search` may perform one authorized exact read after inference if the buyer's simple explicit request is not satisfied by the last verified batch. All prior batches remain recorded and the existing numbered catalog delivery policy proves the delivered result. No changes to the shared domain validator, permanent preference evidence checks, tool registration, external effect execution or receipt authorization. Additional filters and denied/mixed requests are still excluded from narrow recovery. No second LLM or graph.

### Offline diagnostics

`offline_evidence.py` is a pytest plugin that records an allowlisted exception category, phase, exact known reason and allowlisted source basenames/line numbers. The exporter does not emit exception text, locals, raw pytest output, tool arguments or secrets. `run_lane.py` includes `offline_failures` on the two offline base lanes. `run_staging.py` adds case-scoped `offline_failures` on failures and a separately counted `imperfect` lane (nine existing tests), preserving the 22/18 expected counts. The workflow now stores `imperfect.json` via the same safe exporter. The raw JUnit and pytest logs remain temporary and are not uploaded. The paid model diagnostics are unchanged. The same nine imperfect SDK test cases still run before OpenRouter.

## 3. Validation

- Local isolated pytest: 56 passed (22 existing focused cases with updated assertions for changed delivery contract, 27 lifecycle cases including four new, three existing lifecycle evidence cases, four new offline evidence cases). Some dependencies are test doubles; this is NOT an ORM/HTTP/real SDK certification.
- Reproduced the pytest hook through a real intentionally failing subprocess; JUnit extraction preserved source filename and line and omitted injected private text.
- Python AST syntax and YAML parse: pass. Existing package base blobs for both production files, two focused test files, `run_staging.py`, `run_lane.py`, workflow and prior lifecycle evidence file verified against GitHub SHA. No production provider or paid model calls performed locally.
- Original scenario assertions, original base acceptance test file, 18 model cases and nine imperfect SDK scenarios remain unchanged. The focused assertions expecting a repeated monetary number or forced rewrite were intentionally replaced with checks for actual persisted-profile validation and independent search criteria; negative price and permission checks retained.
- Full repository not clonable in this environment; no full Docker, ORM or private SDK run. Results from local doubles do not imply success of CI. No migrations, new environment variables, secrets, dependency changes or production gate changes.

## 4. Upload and verification

1. Extract ZIP and upload the complete files preserving their paths via GitHub Upload files. Verify `.github/workflows/hermes-hei06-controlled-staging.yml` is included; the separately supplied YAML is an identical copy if GitHub omits hidden folders.
2. Commit: `fix(hermes): preserve search autonomy and delivery validation parity`.
3. Check normal deploy and automatic Hermes HEI-06 isolated evaluation. Require offline harness 33/33, isolated PostgreSQL 14/14, and relevant base certification checks; do not infer success of skipped lanes.
4. Run **Hermes HEI-06 controlled staging acceptance** on `main`. It must pass 56 focused/evidence tests, 22/22 original offline cases, 9/9 imperfect SDK cases and the nine existing reporting checks. You can leave `run_openrouter` unchecked for an offline-only test, or check it after base is green; the workflow blocks paid evaluation on any offline failure.
5. Only after successful offline prerequisites evaluate 18 real SDK/OpenRouter scenarios. The acceptance summary cannot authorize production traffic; provider acceptance with real Telnyx/Calendar and controlled rollout still pending.
6. On failure, share the failed step and the artifact (`offline-harness.json`, `offline.json`, `imperfect.json` or `model.json`), rather than rerunning unchanged code. `offline_failures` now provides safe diagnostic locations; a missing location is not proof of a cause.

No remote repositories or production services were modified while preparing this candidate.
