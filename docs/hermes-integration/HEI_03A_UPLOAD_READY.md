# HEI-03A — Native Tool Integration: isolated effect receipts

Base: `08642bb730e5d40dfa91ad083a471444dfead8b9` (HEI-02).
Commit: `feat(hermes): connect native demo effects with transactional receipts`

## Scope and status

This is the first delivery of HEI-03, not the production activation or completion of native tool integration. The existing P04 executor already reuses BlackPenguin appointment scheduling, material coverage/approval, share issuance and the booking/cancellation/rescheduling operation tables. Its boundary remains simulation-only. HEI-03A connects it to the HEI-01B persisted turn and its HEI-02 conversational state, with explicit operator opt-in on the isolated CLI. No production worker, SQL schema, migrations, onboarding, CRM implementation, Firestore, MongoDB, Telnyx or Google Calendar configuration is modified. The global production engine remains LangGraph and the readiness gate remains false.

The new gateway reads a completed, correctly pinned Hermes turn, verifies the exact original sent simulation reply and P08 state receipt, and refuses a pending effect if a newer message or state exists. It requires an enabled tool at both the pinned and current global policy and an executed tool observation from that same turn. It checks the existing business-policy holds. Only a single pending appointment action or a single verified material can run; P04 still performs its own scoped buyer-evidence, consent, availability, authorization and approval validation.

The gateway calls `execute_p04_simulation_operation` using only the stored draft and its inbound ID/revision. On success it verifies the durable `HermesSalesOperation`, operation-specific business IDs and exactly one state revision increment. The operation, a separate deterministic in-app receipt message and `AgentRun.output_snapshot.native_effect` are committed together. The original model message is not overwritten; the native receipt does not have the P08 model-reply lookup key. On an error, this effect transaction rolls back, while the already committed model turn remains available for review. Repeated execution returns the existing native receipt; no second effect or model invocation is needed. The output contains no share bearer token.

A prepared operation is not a result. P04 turn preparation now substitutes a short pending acknowledgement for an uncommitted requested action, instead of allowing a model reply to imply that the action has already completed. Ordinary exploration and confirmation recaps are unchanged by this guard. This does not certify that arbitrary model text cannot hallucinate; real-model evaluation is still required.

## What actually executes when enabled on an isolated staging DB

| Operation | Existing implementation called by P04 | Result |
|---|---|---|
| Book | `sales_crm.scheduling.create_agent_appointment` with sandbox, deferred calendar, no notification | Demo meeting and booking receipt; in-app confirmation labeled as simulation |
| Cancel | Existing Meeting and SalesCancellationOperation models | Demo-only cancellation receipt |
| Reschedule | Existing scheduling and booking/rescheduling operation models | Demo-only replacement and cancellation of previous demo visit |
| Material | Existing sales asset approval/coverage, material snapshot and `asset_share_service.issue` | One scoped share issuance; no URL delivered in this phase |
| Availability | Existing P04 read port and scheduling service | Existing read behavior reused; no new availability system |

Material issuance is not material delivery. The ephemeral bearer URL is deliberately discarded by HEI-03A, including in CLI output and AgentRun; no document is sent, and the safe receipt states that explicitly. Multiple material matches require separate explicit selection and a later batch/share contract. The handoff branch of P04 is not called by this gateway. CRM profile writes are not included.

## Upload (no command required before upload)

Extract the ZIP and upload the complete files at their existing relative paths in BlackPenguin. Use the commit message above. The existing DigitalOcean deployment should still use LangGraph. Also upload the `.github/workflows/hermes-sdk-smoke.yml` file (hidden folder); it was not present in the base tree despite the previous ZIPs. The new isolated smoke workflow builds the pinned SDK image and imports the runtime/gateway. It is independent of the production deploy and does not call OpenRouter. If the hidden folder is omitted by the GUI, create/upload the file separately at `.github/workflows/hermes-sdk-smoke.yml`.

## Optional isolated verification (only when a separate staging environment already exists)

Do NOT point the CLI at production, copy production secrets into a test container, or create a production demo lead to bypass this restriction. The existing image uses the existing pinned SDK Dockerfile. Use a deliberately isolated staging/test DB with a published enabled Hermes configuration, consenting non-deleted demo lead, approved Project, simulation conversation and configured test credentials. The CLI checks environment and bound DB name; a name alone is not a substitute for infrastructure isolation.

Invoke the existing runner as before with the scope arguments and either a persisted inbound or new event/message file, adding `--execute-native-effects`. Example (inside an already configured isolated worker):

```sh
python /opt/hermes-worker/run_staged_simulation.py \
  --company-id "$TEST_COMPANY_ID" --project-id "$TEST_PROJECT_ID" \
  --conversation-id "$TEST_CONVERSATION_ID" --lead-id "$TEST_LEAD_ID" \
  --inbound-message-id "$TEST_INBOUND_ID" --execute-native-effects
```

Do not run this on DigitalOcean production. On a turn with no prepared effect the native result is `no_effect_requested`. On a valid prepared operation the output has a native receipt ID, safe business identifiers and revision; `external_effects=false`. Repeating the command for an already completed event must return the same operation and message IDs with `replayed=true`. The in-app receipt is labeled simulation and external calendar/WhatsApp/SMS are not changed. Native failures return a nonzero CLI status without exposing provider credentials. Review the existing persisted turn and operation records before retrying; never recreate a new event merely to bypass an old operation's guard.

## Local verification and limitations

The 23 new tests use the real HEI-01B staging/receipt router and SQLite ORM stand-ins, with a deterministic SQL-writing double for the P04 executor and a policy-hold seam. They cover one effect per turn, booking/cancel/reschedule/material receipts, no action, stale state and new messages, current policy revocation, missing observations, compliance hold, corrupted run pin, replay, rollback, multiple assets/effects, production/opt-out refusal, and provisional reply behavior. The previously delivered 79 focused tests were rerun together for 102 passed. The full BP checkout, SDK calls and real PostgreSQL/provider integration were not run in this environment. The P04 service itself was inspected in the pinned repository, not executed against real business data. CI and an isolated end-to-end SDK journey remain necessary.

## Remaining HEI-03B work before HEI-04 / HEI-05

1. Native profile persistence using the existing CRM evidence and qualification contract, without making a second LLM the orchestrator.
2. Real delivery contract for approved property documents and galleries; preserve exact provider/outbox receipts, not guessed links or `sent` status. Handle multi-asset menus, authorization and channel policy.
3. Production appointment operation adapter: preserve the existing booking, cancellation/rescheduling, advisor locking, Calendar reconciliation and notification/outbox guarantees; never just remove P04's demo-only checks.
4. Connect the actual worker delivery path and validate ownership/retry/timeout semantics with the SDK process, explicit engine selection, human control and consent. Test real provider and Calendar operations using designated test accounts before any global switch.
5. Confirm the separate SDK image builds and actual model/DB journey passes. Only then proceed with the production readiness decision (HEI-06/07). No silent fallback to LangGraph.

HEI-03A is an intermediate implementation; the user-facing production chat is not yet powered by Hermes.
