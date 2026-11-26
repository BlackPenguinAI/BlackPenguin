# HEI-03B — Guarded production tool adapters (partial delivery)

Base: `1ae9ff0bd50f95c235af0850515e11e9846c51ae` (HEI-03A).
Commit: `feat(hermes): add guarded native production tool adapters`

## Scope and current status

This delivery adds internal production-adapter functions. It does **not** add a
live SDK worker or route, and does **not** certify/enable Hermes on SMS or
WhatsApp. The existing HEI-01A `live_hermes_ready()` remains false, the existing
LangGraph runtime and administrative configuration remain unchanged, and the
P04/P08 simulation restrictions remain in force. No database migrations, new
storage, changes to onboarding, or modifications to current CRM, booking,
material, provider or Calendar service implementations are included.

The production functions are intentionally gated and dormant in this commit.
They reuse the current business service contracts rather than extending the
P04 sandbox executor to real leads. Do not bypass the readiness gate, invoke
these internal functions manually in production, or alter the DB to create the
missing receipts. The caller must own commit/rollback and handle all errors;
there are no new endpoints or automatic side effects.

## Implemented adapters

`backend/app/modules/hermes_sales_core/production_tools.py`:

| Contract | Existing service used | Current scope |
|---|---|---|
| `execute_first_live_booking` | `sales_crm.scheduling.create_agent_appointment`, `first_booking.active_meetings`, existing `SalesBookingOperation` | Guarded first-visit transaction and idempotent receipt, not reachable from the production worker |
| `calendar_snapshot` | snapshot format required by `first_booking.sync_calendar` | Validated `context`, `option`, and `preferences`; Calendar status is pending, not synced |
| `persist_live_preferences` | `sales_preferences`, `commercial_turn`, `lead_profile.resolve/record`, `lead_profile_summary` | Narrow explicit English budget and bedroom declarations; uses existing lead profile JSON, evidence and history. No speculative identity, financing verification, scoring or segment update |
| `prepare_live_material_batch` | `sales_asset_service.approved_for_turn`, `asset_coverage.matches`, `material_delivery.snapshot` | All-or-nothing binding of 1–20 explicitly requested approved files, channel/scope/file/coverage revalidation. Does not issue or send a link |
| `material_delivery_receipt` | Existing SalesMessage, OutboundMessage, SalesAssetShare and `material_delivery.validate_shares` | Exact current share/message/part/provider correlation; returns `provider_accepted` or `delivered` only if proven, never returns a bearer token. No send/retry |

The booking adapter uses the existing 60-minute block (45 minutes plus 15
minutes buffer), existing availability recheck and advisor locking, defers
Calendar synchronization, writes the existing booking operation and Hermes
operation/state receipt in the same caller-owned transaction, and stops the
current conversation's cadence jobs only. It verifies the booking target and
location and refuses a second active visit. The actual Calendar worker must
process the committed receipt; do not describe its pending status as synced.

The profile adapter is intentionally conservative: one direct declaration at a
time, no questions/third-party statements/exploratory searches, matching
permanent state revision and source message, USD explicitly or '$' under an
approved USD project currency. Current staff-verified fields require staff
review; existing CRM source fields and unrelated JSON are preserved. Other
qualification fields (including purchase timeline, multi-fact declarations,
non-USD or ambiguous values, contact identity and scoring) are not covered.

The material adapter handles approved local-file bindings; external URL gallery
resources, numbered offers for multiple subjects, issuance of multiple bearer
links, durable message assembly and actual delivery are still pending. It does
not convert a generic PDF request into a gallery or an unapproved document.
The delivery receipt helper checks exact token hashes in the already accepted
message, current binding integrity and the exact share/outbox association.
`provider_accepted` is not device delivery. Historical receipts must not be
misrepresented as fresh current delivery; expired/revoked bindings need review.

## Required future live-worker contract (not implemented by this ZIP)

The internal guard requires the existing certified engine gate, a scoped real
SMS/WhatsApp lead with granted consent and no opt-out/human pause, an immutable
`AgentRun` (`graph_version=hermes/live/1`, `mode=live`, `status=completed`) with
an exact HEI-01A `sales_engine_pin`, the originating inbound ID, policy version,
continuity epoch, executed tool observation and current tool permission. The
initial provisional reply must be a single-part, accepted provider message
with an exact `OutboundMessage` receipt, explicit lead/project IDs, engine and
run attribution and exact actual content. The future runtime must commit the
scoped `HermesSalesStateEvent` `event_key=hermes:live:<inbound_id>`,
`event_type=outbound_choice_receipt` with the exact normalized state/hash and
revision, linked from `AgentRun.output_snapshot.metadata` to the delivered
message. No P08 simulation receipt meets this contract. New operations require
that the state/message have not been superseded; the caller owns transaction
and recovery. Existing first-booking receipts can be inspected on retries
without booking again, and are historical, not a new appointment.

For booking the actual accepted slot offer, immediate subsequent full recap
(property reference, date, time, timezone, approved visit address) and separate
buyer confirmation must agree. Current P04 only creates a simulation recap;
the live port must include the location and a buyer-friendly name with an exact
reference before this adapter can work. Multiple location selection needs a
supported live location contract. These checks intentionally fail closed.

Do not use the P04 `calendar_status=simulation` snapshot for live reservations.
`first_booking.sync_calendar` expects a `context`/`option` snapshot including
project name, advisor ID, timestamp, duration and location; the new adapter
matches that format. The original Calendar reconciler is preserved unchanged.

## Remaining HEI-03B integration / acceptance blockers

- Connect the isolated Hermes SDK process to the existing worker for inbound,
  resume and follow-up events; preserve event ownership, consent, human control,
  moderation, policy and language boundaries, and never fall back silently.
- Add the live draft port and delivery/state receipt path. Do not reuse the
  simulation channel as a workaround. Validate real multi-turn availability and
  recap continuity; persist current approved property/location evidence.
- Connect native booking/profile adapters, cancellation/rescheduling through
  existing production operation services (including Calendar cleanup and
  notification contracts), and complete broader qualification persistence.
- Issue approved shares and persist their exact durable outbox/delivery intent;
  reuse existing provider dispatch and channel policy, with authorization before
  each part, recovery for failed/uncertain sends and correct idempotency. Do not
  create duplicate shares on retry or leak bearer URLs into diagnostic records.
  The new batch and receipt helpers are not a sender.
- Prove the full path against an isolated PostgreSQL/test environment with the
  pinned real SDK/model and designated provider/Calendar test accounts; only
  then consider a production readiness/selector decision. HEI-04/05 are not
  started by this delivery.

## Upload Ready

Upload all complete files at their relative paths; use the commit message above.
No pre-upload script, patch application, migration, config change or manual
server command is required. The usual deployment remains LangGraph. Include
`.github/workflows/hermes-sdk-smoke.yml` separately if the upload UI omits it:
this file was absent again from the audited HEI-03A commit. The independent
workflow builds/imports the pinned SDK image and checks that live activation is
still blocked; it does not certify model or provider execution. Verify both
workflows after uploading, not just the normal deploy.

## Verification

48 new focused tests passed; cumulative focused HEI subset 150 passed, 18
warnings in 6.43 seconds. Warnings originate in earlier datetime.utcnow calls.
The local harness used the previously delivered SQLite ORM stand-ins and
service doubles, real pure adapter code, and the relevant parser/scope functions
copied from the audited repository. It exercised disabled entrypoints, approved
catalog resolution, calendar snapshot shape, booking-service arguments and
receipt construction, evidence-backed profile records, batch approval/coverage,
provider acceptance and token-hash/outbox/group correlation. It did not run the
complete live guard with real production ORM, full BlackPenguin CI, pinned SDK,
real PostgreSQL locking, Calendar reconciliation or external provider delivery.
The current production entrypoints cannot be invoked successfully until a future
certified live runtime implements the receipt contract. No direct repository or
server changes were made during this work.
