# HEI-06 — End-to-End Evaluation: isolated certification package

**Status: evaluation harness implemented; production certification NOT COMPLETE.**

Base: `f00049e61673e287bb7240cf73ca162cbcc39fa8` (HEI-05), deployment run [45880949169](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45880949169), successful. No production code, schema, credentials, routing gate, deploy workflow, or container topology is changed. The only modified existing files are test fixtures. A new independent evaluation workflow uses the pinned Nous SDK worker image. It does not deploy to DigitalOcean.

## 1. Evidence recovered from HEI-05

`HEI_06_BASELINE_EVIDENCE.json` records checksums, artifact IDs, scope and counts. These results belong to the BASE commit, not the future HEI-06 upload commit.

- Backend JUnit headers: 4,772 tests, 0 failures/errors, 14 skipped. Individual XML testcase elements: 4,653 (4,639 passed, 14 skipped, 0 failures). The discrepancy of 119 entries has not been explained; do not treat the header count as individually verified cases. Three shard manifests agree on the test plan hash.
- 318/318 HEI individual testcase entries pass. The reported 14 skips concern PostgreSQL lanes that need isolated infrastructure.
- Sales acceptance: 136 pytest tests passed; the 64-case matrix says 63 PASS, one NOT_RUN (case 57). The report itself says model quality and live acceptance are not proven. No provider calls.
- Isolated PostgreSQL: 14/14; 11 legacy Sales tests and 3 P07 Hermes contract/migration tests. The latter use a minimal contract ORM, not the full live worker.
- Frontend image build: PASS. No dedicated HEI-04/05 Vitest evidence from the deployment workflow.
- SDK smoke workflow absent from the base tree. Real SDK / paid inference / real channels / Google Calendar not certified.

## 2. Upload and run

1. Unzip and upload repository-relative files. Commit: `test(hermes): add isolated end-to-end certification lanes and evidence reports`.
2. GitHub web uploads often omit hidden `.github` directories. **Verify the workflow exists at `.github/workflows/hermes-hei06-evaluation.yml` in the committed tree.** If missing, upload the standalone YAML directly inside `.github/workflows` with that exact name. No local patch or script is needed for upload. Creating/modifying workflows requires the appropriate repository permission.
3. Confirm the ordinary deployment succeeds. In Actions, open **Hermes HEI-06 isolated evaluation**. The workflow runs on qualifying pushes; use `Run workflow` on main if necessary. The default `run_openrouter=false` runs offline and PostgreSQL/Angular lanes only. This is separate from production deployment.
4. To run real inference, create a dedicated, low-budget OpenRouter API key (synthetic evaluation only), add it as repository Actions secret **`HEI06_OPENROUTER_API_KEY`**, and explicitly run the workflow with `run_openrouter=true`. Do not paste the key into chat or commit it. It is used only in the optional inference job, not passed to the offline/PG job. There are 4 cases (2 scenarios x 2 independent repetitions), at least 8 model turns plus tool iterations. Model fixed to `openai/gpt-4o-mini`. No automatic retry-until-pass. Stop/control is deterministic. Charges may apply; the dedicated provider key's spend cap must be configured outside this workflow.
5. Download the artifacts named `hei06-offline-postgres-<sha>`, `hei06-frontend-<sha>`, `hei06-openrouter-<sha>` and inspect Actions job results for the exact uploaded commit SHA. A skipped job, missing report, mismatched commit, failed build or omitted test is not certification. If a lane fails, report its job and sanitized artifact; do not loosen the assertion or gate just to obtain green CI.

The independent workflow is the replacement for the previously omitted `hermes-sdk-smoke.yml`; do not need both workflows for these checks. It builds the exact SDK pinned to `b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb`. The installed distribution metadata is checked. Build/import success alone proves neither inference nor live operation.

## 3. Candidate lanes

| Lane | Cases | Infrastructure | Success condition |
|---|---:|---|---|
| SDK build/import + private route smoke | 2 commands | Pinned isolated image, no network during execution | Both exit 0, gate stays closed |
| Offline fixture | 1 multi-turn case | Actual ORM, private ASGI endpoint, SQLite, double of model and messaging | All assertions pass |
| Actual PostgreSQL worker | 14 | Disposable PostgreSQL 16, per-test schemas, internal network; actual BP ORM; model/provider doubles | 14 PASS, no skip, no duplicate cases |
| Frontend | 14 | npm lockfile, Vitest/jsdom, Angular production/offline-ci compilation | All 14 tests and build pass |
| Real SDK inference | 4 | Pinned Nous SDK and dedicated OpenRouter key; synthetic data, private ASGI, SQLite, fake provider | All 4 cases pass with correct facts, tools and receipts |
| Controlled real provider acceptance | Manual, pending | Isolated staging test numbers and Calendar accounts only | Authenticated genuine callbacks and exact external effects reconciled |

The ASGI test uses the actual authenticated `/internal/prepare` route and a distinct database session, not the actual HTTP network/socket/container topology. The provider double explicitly records acceptance, **not handset delivery**. No provider or Calendar credentials are included. Offline test lane has a test-local readiness override, not an environment switch or a production change. The reporting tool fails on absent/duplicated/skipped cases and exports only counts, expected revision and status; model outputs, raw provider responses and credentials are not uploaded. If a real model test fails, reproduce only in a secure synthetic environment with the dedicated key; do not dump provider credentials or customer data to public logs.

### 3.1 PostgreSQL cases

1. Native worker turn and accepted receipt.
2. Queued receipt reconciled once, no second provider send or inference.
3. Unknown receipt requires review, no resend.
4. STOP without SDK invocation.
5. Human handoff without SDK invocation.
6. Private preparation releases DB transaction before inference.
7–8. Real state ORM competing first/existing-revision writers: one commit, one conflict.
9. Approved local material issue and exact replay, no duplicate shares.
10. Native booking with exact retry, one 60-minute reservation.
11–12. Cancel and reschedule through native services, exact retries.
13. Unavailable replacement preserves original reservation.
14. Two workers competing for one claimed job, one winner.

The fixture defaults to in-memory SQLite in all existing suites. Only explicit evaluation fixtures opt into PostgreSQL. PG creates a unique schema per test and drops that schema only. CI creates an internal Docker network and a dedicated PostgreSQL 16 server with no published ports; the test requires the exact synthetic database/user/hostname, no production DB URL. No migrations or tables are added to BlackPenguin's production schema.

### 3.2 Real inference scenarios

**A (twice):** Ask for number of bedrooms in Van Buren → verify tool, name, correct 3-bedroom fact and stored focus → ask “Can you send me the PDF?” without naming the property → require executed material tool, exactly one approved asset share for Van Buren, completed native operation, provider-double acceptance, stable focus → retry claimed job, no new inference/share/send → STOP, no inference.

**B (twice):** Ask for available 3-bedroom houses under $350,000 in a numbered list → require tool execution and exactly two proven menu choices → ask “The second option. How many bathrooms does it have?” → require the actual persisted second choice as focus, correct name and 2-bathroom fact, no hardcoded menu order. No LLM judge and no hidden replacement of model output. These are minimum signal scenarios, not an exhaustive model-quality benchmark.

## 4. Required controlled staging evidence before HEI-07 activation

Do not modify `live_hermes_ready()` based solely on the workflow. HEI-06 must close the outstanding gates with an approved, isolated staging setup (not the production database or real customer contacts). Separate infrastructure/credential setup is not provided by this test-only delivery. Tests below must use explicitly owned numbers or consenting test participants, a dedicated Telnyx test route/account and Google test calendar, verified approved synthetic catalog and a staging database. Obtain explicit authorization before sending actual SMS/WhatsApp or creating Calendar events. No readiness monkeypatch in production.

| Gate | Required evidence |
|---|---|
| SDK and transport | Actual pinned private service on internal network, authenticated request/response, wrong token 401, no public port, timeouts preserve reservation/draft, crash/retry does not call second engine |
| Actual published policy | Evaluate exact intended model/prompt version/tool list, not only synthetic baseline; pin commit, SDK hash, image digest, policy ID and model |
| Conversational parity | Named/ordinal references, implicit PDF, ambiguity, temporary vs permanent preference, no-match search, budget cap, date/time menus, location, language, multiple consecutive inbound, human takeover/resume, explicit engine transition. Use at least 3 paraphrases per P0 scenario. Verify buyer-visible fluency and exact state, not only successful tool calls |
| SMS | Approved outbound to test number; verify authentic Telnyx inbound event, outbox and status callback; accepted vs delivered, duplicate callback, queued, undelivered, unknown receipt and STOP; no blind resend |
| WhatsApp | Test number + approved messaging setup; in-window conversation, template/window restrictions, authentic receipts and duplicate callbacks, opt-out |
| Calendar | Dedicated advisor calendar; verified availability then explicit recap/confirmation; exactly one event + local meeting; duplicate retry, cancellation, rescheduling, replacement failure retains original, pending/failed sync visible |
| Data integrity | PostgreSQL worker suite + concurrent two-worker claimers; no duplicate booking or share; approved resource only; cross-tenant and deleted-lead denial; stale consent/epoch denied immediately before effect |
| Operator UI | Inspector matches actual persisted state/receipts; no sensitive data; HEI-05 selector and both editors accessible to Superadmin; unauthorized role refused |
| Rollback | Pin existing in-flight event to original engine, explicit new event ownership after selection, preserve appointments/history, revoke stale offers, rehearse rollback without replay or fallback |

Required: all deterministic P0 cases pass, no skips; zero unauthorized effects, tenant data leaks, duplicate sends/bookings/shares, false claims of confirmed operations, or silent engine fallback. Any uncertain/partial effect remains in review. Quality review on actual model output and channel delivery is mandatory. Existing limitations (rapid messages outside guarded resume, actionable menus split over messages, uncertain partial sends, historical routes outside the router) remain explicit staging blockers until their behavior is accepted or corrected. Do not certify the entire integration from four model cases.

## 5. Local validation for this package

Verified base API ZIP SHA-256 `4b1ab7fa3c3d9399a75588181893490fc78ed091bd9891549c061a46a2586b17`, internal API tar checksum, tag, and matching dependency-layer identities with previous locally extracted image. Used exact base app source with matching Python 3.12 image dependencies. The two modified fixture bases match their Git blob SHAs (`6808f8cbb63c78698544f6cace1db5c10844becf`, `52bb3456f5a79c0e9f4f083e6338129da9d41894`). Local affected groups: 38 previous worker/changes tests + 77 prior continuity/contracts/inspector/admin tests + 1 new offline case = **116 passed** (the final ASGI harness rerun passed independently). The 14 PG and 4 actual inference cases were collected, not executed. Docker/PostgreSQL and SDK installation are unavailable in this local environment; Angular dependencies not available. Workflow YAML parsed; its remote execution has not been performed here.

**Next:** run the candidate evaluation workflow, then resolve its failures and complete controlled staging acceptance above. HEI-06 remains open. HEI-07 cannot start productive Hermes routing until evidence is approved. LangGraph remains active. No direct repository or production changes were made by this delivery.
