# Groups 7–9: grounded drafts, staff diagnostics and selective shadow integration

Base: 75ee12ab86db7ecb6da0e21cf887ca0cf5c2cee9 (groups 1–6).

## Delivery status

| Group | Delivered | Not claimed |
| --- | --- | --- |
| 7 | Deterministic grounded draft composition, validation and channel splitting | Live LLM response-quality certification or customer delivery |
| 8 | Published versioned staff settings, monitor inspection and diagnostic exports | Changes to production settings or access to a customer's account |
| 9 | Scoped shadow hook in the worker, kill switches, compatibility/regression checks | Active replacement engine, transactional action adapters or complete real E2E certification |

Group 9 remains **partially open**. This is not a release that should be enabled
to replace lead-facing responses. Shadow mode evaluates alongside the existing
engine; it does not deliver the new draft or change an appointment/CRM status.

## Group 7

The composer consumes typed tool results, not arbitrary model-generated prose.
Every included fact comes from the earlier approved-context tools. Explicit
restrictions and cancelled alternatives filter the result. Catalog summaries
include all returned property types with paragraph/list separation and preserve
each currency independently. Concise/detailed catalog styles are selectable;
selected-property details additionally include the approved description/features.

Textual answers and explicit information gaps precede material proposals.
An available PDF is not hidden because prices are unknown; missing prices
remain pending and are disclosed. Possible embedded photo coverage is qualified,
not asserted as verified. A material is labelled not sent and represented by
approved asset IDs, not a credential-bearing diagnostic URL. No email/booking/
handoff confirmation is invented. Unsupported structured fact shapes produce
a validation violation instead of raw object/JSON text in a lead draft.

Validation/repair is deterministic recomposition from recorded results plus the
existing lossless renderer/splitter; it does not repeat tool operations. This is
not a free-form LLM writing agent. The draft records answered/pending task IDs,
asset IDs and violations. Earlier lookup-state completion is not evidence that
the lead received a file; customer fulfillment must use the final draft and
future dispatch receipts, not lookup status alone.

## Group 8

AI Settings / Sales Agent has a staged-engine section using the existing
draft/publish/history/restore mechanism. runtime_config is part of the Sales
configuration, not a separate mutable global switch.

Supported settings:

- mode: disabled or shadow. Active mode is rejected by the backend.
- company_ids and project_ids: required allowlists in shadow mode, canonical
  UUIDs without wildcards. Both must match; this is not an OR selection.
- lead_ids: optional further narrowing.
- max_steps (1–30), max_seconds (greater than 0, at most 30).
- understanding_guidance: versioned reference guidance; cannot override the
  fixed schema, evidence checks, authorization or action safeguards.
- composition_style: concise or detailed.

Editing/saving a draft does not activate shadow evaluation; publication is
required, as are both server gates. Old configurations default to disabled.
Invalid settings return readable field-specific 422 text without echoing secret
inputs. Existing published identity/protocol/guardrail prompts are not replaced.
The group-3 request snapshot now includes the applied runtime configuration as
reference data, so guidance used at evaluation time remains recorded.

/monitor remains hidden from menus and superadmin-only. The chat view displays
the latest 20 staged events in expandable, escaped JSON. It clears these records
on scope change and ignores stale responses through the existing generation
guard. Full audited JSON exports include all scoped dialogue states/events,
not only the latest 20. Existing credential/query/share-token redaction and
company/project/conversation/lead scoping apply to the new evidence too.

## Group 9: delivered shadow path

The worker invokes a guarded observer after its existing consent/pause/mandatory
intervention checks and before ordinary legacy routing. With gates off it
returns before querying configuration or calling a model. Selected cohorts
require BOTH server gates and a published scoped policy. The observer:

1. Imports selectable IDs from the latest scoped outbound message. A plain new
   reply invalidates unqualified old ordinal offers; no catalog reordering or
   filtering is used to remap an option's index. Appointment offers expire after
   30 minutes in this bridge.
2. Records the group-3 interpretation, executes the group-6 bounded read runtime,
   composes a draft and stores a final not_dispatched event.
3. Keeps stable event keys to avoid repeating a committed evaluation, including
   recorded failed interpretation outcomes.
4. Uses a savepoint for atomicity and caller-owned commit/rollback. SQLite's
   physical outer transaction is established explicitly before that savepoint.
5. Bounds inference with an async timeout; synchronous read-tool budgets remain
   cooperative. A selected shadow run adds latency/model usage; it is not a
   free, background-only evaluation.
6. On failure, preserves a safe error-code event where scope/storage remain
   available. It never pauses the lead, substitutes a response or includes a raw
   provider error in a customer message.

The legacy result, escalation, appointment/share rules and outbound dispatcher
remain authoritative. This is intentional isolation, not proof that legacy
semantic mistakes have been corrected by the new draft.

## Installation and rollback

Copy the differential backend/, frontend/ and docs/ files over the base.
No new migration: head remains 20261106_sales_dialogue from group 1–3.
Keep these gates false in the default deployment:

    SALES_DIALOGUE_RUNTIME_ENABLED=false
    SALES_UNDERSTANDING_PREVIEW_ENABLED=false

This task does not change server environment or published staff settings.
Shadow can be enabled later only by an authorized operator for a selected test
cohort. It can incur LLM costs using the configured Sales model. No such paid
call was made in the supplied tests.

To reverse shadow evaluation, publish mode=disabled or turn off either server
gate and restart the affected processes. This stops subsequent evaluations;
it does not promise cancellation/refund of an already-running provider call.
Do not delete historical events or downgrade evidence tables.

The JSON export has additive dialogue_states/dialogue_events fields. Consumers
should accept these optional additions. The earlier documents remain historical
delivery records; this document describes the additional current path.

## Checks

Backend:

    python -m pytest tests -q
    python -m pytest tests/test_sales_delivery_789.py -q

Frontend:

    node -e 'const fs=require("fs"),cp=require("child_process");const config="tsconfig.sales-789.spec.json";const includes=JSON.parse(fs.readFileSync(config)).include.filter(p=>p.endsWith(".spec.ts"));cp.execFileSync(process.execPath,["node_modules/@angular/cli/bin/ng.js","test","--no-watch","--ts-config",config,...includes.flatMap(p=>["--include",p])],{stdio:"inherit"});'
    npm run build -- --configuration production

These include real FastAPI TestClient/SQLite checks, Angular DOM tests, the
existing 27-issue regression inventory and a worker integration test with fake
model/provider boundaries. They are not a browser-driven authenticated E2E run.
Two PostgreSQL concurrency cases still need a disposable PostgreSQL database.

## Work required before group 9 can be closed

- Integrate real transactional booking/share/CRM/consent/handoff adapters with
  permissions, fresh approval checks, action consent and provider/outbox
  idempotency. Earlier groups deliberately denied these effects.
- Complete the explicit persistent-restriction release workflow; do not clear a
  saved prohibition merely because the model now proposes an affirmative action.
- Validate a disposable PostgreSQL environment, authenticated browser paths and
  test-lead end-to-end scenarios. Do not substitute production destructive tests
  or an automated message to an unapproved telephone number.
- Benchmark the configured real model against the cases. Scripted outputs do not
  prove intent/negation comprehension, conversational quality or safe autonomy.
- Only then add/select an active replacement mode with a controlled rollout and
  tested rollback. This delivery intentionally rejects such a mode.
