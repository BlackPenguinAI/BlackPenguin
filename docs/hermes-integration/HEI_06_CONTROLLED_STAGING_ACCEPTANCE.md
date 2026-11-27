# HEI-06 — Controlled Staging Acceptance (evaluation package, not production activation)

## Verified baseline and intent

- Candidate: `b87f3d9013614ae46c2b8e5d0ccea61427568beb`.
- [Deployment #474](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45939034336): success.
- [HEI-06 evaluation #16](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45940671973): all four jobs successful; artifact 15173041300 SHA-256 `73d5bfc096f0b84409489b0d64426902db179c457d1664efff34ffa7f3cbe4b3` records 4/4 real SDK scenarios, zero failed/skipped/duplicate cases.
- Demo reference: `jorgektch/testing-hermes-agent` at `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`, especially `backend/app/hermes_runtime.py`, `delivery_policy.py`, `property_options.py`, `v1333_contextual_choices.py`. Retain Hermes interpretation/tool autonomy and domain-owned verified facts, presentation, authorization, persistence and effects.

This delivery adds only evaluation files and a manually dispatched workflow. It does not change production Python, Angular, database schemas, production compose/deploy, the original HEI-06 workflow, published policy or global engine selection. LangGraph remains available and the hard `live_hermes_ready()` gate remains closed. No public SDK port is introduced. The original four-case evaluation remains a separate regression lane.

## 1. Upload and execute

Commit: `test(hermes): add controlled staging acceptance and private HTTP evaluation`

1. Unzip and upload the contents preserving repository-relative paths. No scripts or patch application before upload.
2. Verify `.github/workflows/hermes-hei06-controlled-staging.yml` exists on `main`. Web uploads can omit hidden directories. Upload the standalone YAML directly to `.github/workflows` if needed.
3. Verify the ordinary BlackPenguin deploy and existing isolated evaluation. Then open **Hermes HEI-06 controlled staging acceptance** in Actions and select **Run workflow** on `main`. For the full expanded inference lane, check `run_openrouter` and run a new manual execution. The existing repository secret `HEI06_OPENROUTER_API_KEY` is reused. No extra repository secret or change to production `.env` is required. Do not paste credentials into chat or Git.
4. The new workflow is manual-only; it never automatically spends inference credit after a push. With the option off, only the offline/private-network lane executes. With the option on, the model lane runs only after offline success. The model lane comprises 18 independent conversations, 39 planned ordinary inbound inference turns (3 focus-media, 2 ordinal, 2 temporary, 1 no-match, 1 comparison and 4 visit turns per variant), plus model tool iterations and deterministic STOP/replay paths. Use the dedicated provider key with a provider-side spend limit. Do not rerun until green; preserve failures and diagnose.
5. Inspect both artifacts, their exact candidate SHA, SDK revision and per-case status. A green offline-only run is NOT real inference acceptance.

## 2. New evaluation lanes

| Lane | Expected | Actual infrastructure | Exclusions |
|---|---:|---|---|
| Closed private Docker network | 5 HTTP assertions + 3 topology assertions | Actual standalone Uvicorn process and another container; alias `bp-hermes:8080`; internal network; no published port | No DB, real LLM, providers, or gate override |
| Socket transport | 4 tests | Actual Uvicorn loopback TCP and real `request_sdk_draft`, fixed ID-only JSON contract, authentication and same production receipt validation; per-test shared SQLite | Same process threads, model/provider doubles, test fixture readiness override |
| Expanded scenario harness | 18 tests | Actual worker, isolated ORM, real tool adapters, same TCP path, model/provider doubles | Not model quality or external delivery evidence |
| Evidence/comparison negative controls | 9 tests | JUnit identity, completeness, secret projection and swapped comparison facts | No network |
| Expanded actual SDK | 18 scenarios | Pinned Nous SDK and OpenRouter, TCP loopback, synthetic published baseline and SQLite, provider doubles | Not actual production policy, provider delivery, production container topology or combined real PostgreSQL+real model |

The internal Docker network stage uses the exact pinned Dockerfile and normal `sdk_service:app`, starts one worker with no host port, verifies Docker network isolation and uses a separate probe container. Wrong/missing token returns 401, malformed body 422, correct token still returns 503 because the unmodified gate is closed, and OpenAPI is unavailable (404). It does not prove successful inference between two active containers.

The expanded real-model lane does not replace `AIAgent` or tool results. It observes the runtime/prepare boundary and records sanitized tool statuses, known error categories, safe response shape and last checkpoint. Per-case success requires every assertion and a complete trace. Missing, duplicate, skipped, incomplete or unknown cases fail. Temporary JUnit/logs are not uploaded. The model is fixed at `openai/gpt-4o-mini`; SDK revision is verified through distribution metadata (`b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb`). The only readiness override is already present in the disposable pytest fixture, not in the standalone SDK process or deploy config.

## 3. Parity scenarios — buyer outcomes, not predetermined tool paths

Each family uses three distinct message formulations; each starts with a fresh isolated database, approved catalog and synthetic lead. Van Buren (3 bedrooms, 1 bathroom) and Oakwood (3 bedrooms, 2 bathrooms) have different price and bathroom values to detect focus errors. The temporary-search family adds Cedar Grove (4 bedrooms, USD 375,000) outside the buyer's permanent USD 350,000 cap but within the explicitly requested temporary cap. Appointment windows use two future local dates with two 60-minute slots each; exact choices are derived from the actual delivered menus rather than a guessed model order.

| Family | Mandatory outcome |
|---|---|
| Focus and implicit PDF | Read Oakwood, explicitly switch to Van Buren, correct detail, share only approved Van Buren PDF, exact receipt and replay without a duplicate, STOP without inference. |
| Property ordinal | Search and actually deliver a menu containing both approved properties, preserve order, select the displayed second option, answer its distinct bathroom count. |
| Primary vs temporary | Explicit lasting budget/bedrooms persisted with inbound evidence; a later exploratory higher-cap four-bedroom search returns Cedar Grove; original preference revision and values stay unchanged. |
| No match | Execute the explicit six-bedroom/low-cap search; zero matches, no phantom menu, communicate lack of matches; if alternative is mentioned it must be distinguished from a match. |
| Comparison | Both distinct approved bathroom counts correctly associated with their names. No booking or material effect. |
| Visit | Verified day menu, second day, verified time menu, second time, delivered recap, no reservation until later explicit confirmation; exact property/advisor/date/time, 60 minutes, one native meeting, pending Calendar operation, no external event; replay does not send or book again. |

Some capabilities (e.g. date/slot recap wording) may fail with the actual model even when the offline harness is green. That is meaningful certification evidence. Do not relax the business contract just to pass. The suite does not cover every potential phrasing, does not certify complete language fluency, and does not require a read tool when facts already exist in the context. State-changing effects require domain evidence. A later production policy may differ from this synthetic baseline.

## 4. Local validation performed on baseline code

- Verified hashes of 16 existing files against the exact GitHub tree, including the runtime, SDK service, transport, live preparation, domain read/operational ports, state-facing production tools, numbered catalog, fixture and evaluation helpers.
- 31/31 passed in the API image Python environment with real ORM, SQLite, real HTTP on loopback, simulated SDK and provider where applicable; 18 scenario harness + 4 HTTP + 9 evidence/comparison checks. Final run: `31 passed, 2985 warnings in 17.39s`. The test-only API key had to be set to the explicit synthetic sentinel `test-only` (the earlier local script used `testing-only`), then the suite passed.
- 18 real-model tests collected; NOT RUN locally. No Docker daemon/CLI or dedicated external provider credentials available here. Docker topology stage, pinned SDK installation in this new workflow and the 18 real-model cases require CI evidence. Previous 4/4 real inference evidence applies to the baseline, not the new workflow run. Previous 449 local tests were not rerun for this test-only delivery. No new production code modified.
- YAML parsed and shell scripts checked for syntax; no public port flags or deployment actions. Do not treat static checks as an executed CI workflow.

## 5. Controlled external provider acceptance (still NOT_RUN)

Read `HEI_06_REAL_PROVIDER_ACCEPTANCE.md`. It is a runbook and evidence checklist, not evidence of an executed send or a provisioning script. The service must first be deployed to an isolated, active staging stack with a deliberately scoped, reviewed staging authorization mechanism. Never set the production global gate to `True` or install a test fixture into a production service just to perform a test. The workflow in this delivery cannot open a gate. The remaining setup includes separate staging DB, dedicated test-only endpoints and accounts, exact intended policy, isolated active service topology, signed provider callbacks, and an explicit route limited to approved test contacts. Review and authorize that environment before any real effects.

Exit HEI-06 only with the baseline regression, expanded conversation outcome evidence (review failed cases), active private service cross-container request/receipt, actual published policy, authorized Telnyx/Calendar acceptance, operator/UI scope and rollback rehearsal. A pass in the new workflow is necessary evidence, not sufficient proof of readiness. No automatic cutover; HEI-07 will implement the explicitly authorized deployment/activation after acceptance. Keep the engine selection and historical pins intact.
