# HEI-06 — Real provider acceptance checklist (NOT_RUN)

This document defines the remaining external acceptance. It does not authorize sending or booking. No credentials, contacts, events, provider URLs, customer transcripts or tokens belong in this repository or the GitHub artifacts. Do not execute the checklist against production leads or production Calendar. All checks start with an explicit approved staging session. Use dedicated test participants and operator-owned numbers, and a dedicated Calendar with no customer events. Staging operator must be able to stop dispatch immediately.

## A. Provision and attest before opening any staging traffic

Record the full candidate SHA, API/worker/SDK image digests, SDK revision, exact intended published policy ID/version/model and fingerprint of prompt+tool configuration (hash only). Record date UTC and reviewer. Verify the same candidate passed the original HEI-06 and controlled staging workflows. Reuse only synthetic catalog and leads. Keep the global production selector LangGraph; no automatic fallback.

| Dependency | Required isolation and proof |
|---|---|
| Data store | Dedicated staging PostgreSQL (and any necessary other staging services); no production URL, snapshot or contact data; use normal migration/deploy discipline only in staging. |
| Service | Single non-root SDK instance from pinned Dockerfile; internal DNS `bp-hermes:8080`; no published port; private HTTP token shared only by staging worker/SDK. Verify wrong token=401 and malformed input=422. The closed-gate probe alone is not evidence of an active service. |
| Activation | Review an explicit staging-only authorization boundary before processing actual jobs. Current production gate remains hard closed. Do not monkeypatch readiness in the live service. Confirm the approved staging allowlist is enforced before enqueue, before effects and immediately before provider dispatch. |
| Model policy | Publish the intended configuration into staging using normal administrative controls. Compare policy ID, model, prompt hash, tool list and iteration limit to the intended deployment. No raw private prompt in public evidence. |
| Telnyx | Dedicated test number(s), messaging profile, WhatsApp business/test configuration if supported, staging callback destination and signature verification. Confirm test recipients explicitly consent. Confirm real recipients cannot route to staging. |
| Calendar | Dedicated staging Sales user and connected Google test calendar. Only synthetic blocks/events. Use distinct OAuth configuration/credentials; do not share production accounts. |
| Safety | Operator-owned stop switch/pause, verified dispatch deny outside test allowlist, explicit STOP handling, dedicated low-budget key, no automatic follow-up to uncontrolled recipients. |

All checks above require actual provisioning and authorization, neither performed by this delivery. A failure or missing dependency means NOT_RUN, not PASS. This checklist is not a command to send real messages; obtain explicit authorization and confirm actual recipient and calendar before any test send or create.

## B. Execute in approved controlled staging

For each test record UTC start/end, candidate SHA, anonymized correlation identifiers (hash of message/event/meeting/operation/run IDs), observed provider status, expected/actual counts, operator and PASS/FAIL/NOT_RUN. Evidence should link to restricted dashboards or sanitized reports without copying bearer tokens, access URLs, recipient numbers or customer content. Review actual message wording with authorized reviewer; record outcome rather than logging text publicly.

| ID | Test | Mandatory evidence and pass criteria |
|---|---|---|
| HTTP-01 | Active worker -> private SDK over real network | Authenticated job/run IDs, one prepared draft, exact pinned policy, actual receipt; no public port. Wrong auth or unreserved run must fail without side effects. |
| HTTP-02 | Timeout/crash and exact retry | Stop/restart the test SDK on a synthetic turn; same reserved event preserved or moved to review, no duplicate inference after durable draft, no duplicate message, no implicit fallback. |
| POLICY-01 | Intended published version | Actual AgentRun pin matches intended policy/version/model and candidate. Replay retains original pin; disabling policy prevents new unsafe effects. |
| SMS-01 | Real inbound and outbound | Owned test number sends named-property inquiry. Authenticated Telnyx callback, exact scoped inbound, AgentRun, outbox and actual provider receipt. Verify actual device receipt separately from provider accepted. |
| SMS-02 | Implicit brochure | Send follow-up without property name. Approved material only, correct property, receipt correlation and real link access by tester. Replay same verified event: no extra share/send. Never log bearer URL. |
| SMS-03 | Retry/duplicate/unknown | Reconcile genuine callback twice, one outbox and one state revision; ambiguous delivery moves to review, no blind resend. Do not manufacture a receipt as if genuine. |
| SMS-04 | STOP | Send STOP from test number; consent/opt-out persisted, no further automatic outreach, no model invocation for STOP. Reset only with explicit authorized test procedure. |
| WA-01 | In-window WhatsApp | Genuine test inbound; authorized reply, PDF/approved gallery and handset verification; no cross-channel leak. |
| WA-02 | Window/template boundary | Outside the customer-service window, unapproved free-form outbound must be blocked. Use only dedicated test setup and approved template when needed. No bypass of channel restrictions. |
| CAL-01 | Native availability | Insert synthetic test calendar conflicts and available slots; verify only actually free windows are offered, project timezone and 60-minute slot (45+15) correct. |
| CAL-02 | Book | Select day/hour from delivered menu, assert no booking prior to explicit recap confirmation. Confirm separately; one local Meeting and one genuine Google event on test calendar, correct advisor/property/date/time; provider delivery and calendar sync state distinguished. |
| CAL-03 | Retry | Reconcile same operation/callback; event and meeting count remain one; no duplicate booking, no silent cancellation. |
| CAL-04 | Reschedule | Confirm exact replacement, verify new event/time and old cancellation state, exact native receipts; deliberately unavailable replacement preserves the original appointment. |
| CAL-05 | Cancel | Explicit cancel request and separate confirmation; verify cancellation on test calendar and local record; retries do not create new events. |
| CONTROL-01 | Human control and resume | Pause test lead, send multiple authenticated inbound messages, resume via supported workflow; state and original IDs preserved, stale proposals invalidated; partial/uncertain effects require review. |
| CONTROL-02 | Rollback rehearsal | With isolated staging only, select LangGraph explicitly, prove historical/in-flight pins unchanged; new eligible event uses new selected engine, no silent fallback, no duplicate response or destructive DB change. Restore reviewed staging selection if needed. |
| UI-01 | Inspector | Verify actual engine attribution, focused property, primary/temporary preferences, calendar and provider status against stored evidence, not only visual appearance. Unauthorized role/other tenant/deleted lead denied. |

## C. Final decision

All deterministic safety/effect tests must pass with no skips before live activation is considered. Zero unauthorized contacts, data leaks, stale confirmations, duplicate native effects or unproved claims of confirmed bookings. If an external receipt is uncertain, preserve original state, stop that test and reconcile with authorized operator; never generate synthetic provider receipts as evidence. Keep provider acceptance and device delivery distinct. Keep confirmed local reservation and Calendar synchronization distinct. Review availability and language quality using actual conversations, not just pass flags.

Clean up only test data/events using the authorized staging operator process; never delete production or shared resources. Close staging dispatch on completion. Report remaining blockers and attach the restricted evidence references. No automatic readiness flag or selector mutation is generated by this checklist.
