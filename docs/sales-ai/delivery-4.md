# Delivery 4 — Takeover, Resume and inactivity

Base: `aa284be22377517169cd7b668a507927b5a25cbe` (Delivery 3).
Scope: SA-07 and SA-08. The current Sales workflow remains mandatory for all
eligible Projects; no rollout flag or new Company onboarding is required.

## Human control and continuity

Pausing creates a new persisted control epoch. Pending/claimed inbound work is
held for Resume rather than replayed after an administrator takes control.
Authenticated provider messages received while paused are retained, identified
individually and marked unanswered; explicit opt-out still queues protected
processing. No ordinary Sales effects run while paused.

A provider-accepted manual reply records exactly which pending message IDs it
answered. Messages arriving during the provider call remain pending. An immediate
send failure is not an answer; a later undelivered manual receipt also makes its
original inputs eligible for review/continuation. Provider acceptance remains
distinct from delivery to a phone.

Resume after a manual answer waits for the lead unless newer unanswered messages
exist. Without a manual answer, one durable `resume` job consolidates the pending
inputs. Repeated Resume on an already active conversation does not enqueue another
turn. A new inbound message supersedes a queued/processing continuation and joins
the new input set; no indiscriminate history replay is performed. If nothing is
pending, the agent waits rather than sending an unsolicited repeated answer.

Consolidations are stored as internal context with immutable source-message IDs,
not provider messages. The conversation view labels them explicitly. Exact evidence
must belong to one original input, not span several messages. Profile facts retain
original-message provenance plus the internal context ID. Internal contexts do not
inflate the engagement message count or appear as a new lead message in summaries.
The interpreter protocol is `sales-understanding-prompt/2.11`.

Pause, accepted manual answers and Resume invalidate old offer/confirmation
contexts. Current interest, restrictions, profile and actual reservations remain
separate and are retained. A bare "yes" cannot authorize an old or human-authored
offer. Epoch checks after inference, before effects and at provider dispatch stop
responses prepared before a takeover; provider delivery retains stable idempotency
keys. Uncertain sends go to review instead of being automatically resent.

A pending consolidation over 12 KB or a failed interpretation stays reviewable;
it is not silently truncated or marked answered. Staff can answer manually, then
pause/Resume as appropriate. Historical messages are not reinterpreted merely by
deploying the release. Existing scoped incident resolution and false-positive
audit remain in force, and Resume cannot remove opt-out or missing consent.

The mirror shows pending message counts, waiting for the lead, continuation/closing
job state, the last response role/status/engine, and a scoped handoff summary:
current enquiry and visits, qualification, segment, open objections, pending topics
and suggested operational next step. Processing errors and control supersession
are distinguished from a conversation that is still paused. Restricted Schedule
contexts do not expose that summary.

## Inactivity and commercial cadence

A separate durable `inactivity` job is scheduled after a genuine answered exchange,
including a manual answer followed by Resume. Default: **45 minutes**, configurable
in published AI Sales settings from 5 to 240 whole minutes. First contact templates
alone do not create a farewell. The fixed English closing invites the lead to
return without pretending to be a human.

Each response episode can close only once, including across repeated pause/Resume.
A new inbound cancels the previous closing; retries keep the same outbound key.
Silence does not unsubscribe a lead, pause the conversation or cancel a visit.
Closing is skipped for pause, withdrawn consent, opt-out, queued/failed inbound
work, unavailable channel window, quiet hours, changed opportunity, readiness or
booking/cadence restrictions. A closing expires 15 minutes after its due time;
it is skipped rather than deferred for days.

Commercial cadence remains a distinct job kind and uses the published hot/warm/cold
hours on Resume as well. Pending inbound/takeover work takes precedence over nurture.
The simulation uses that same published cadence and executes inactivity work through
the virtual-clock/in-app adapter without contacting external providers.

## Deployment and compatibility

Migration `20261109_sales_continuity` follows `20261109_sales_asset_coverage`.
It adds `sales_conversations.continuity_json` and follow-up `kind`, `payload_json`
and `claimed_at` fields, with additive defaults for existing rows. Old jobs remain
`cadence`; upgrade neither starts new conversations nor schedules historical
farewells. Downgrade removes the dedicated jobs before dropping their discriminator
so an older worker cannot send them as nurture messages. Conversation/message audit
records remain available.

Deploy API, worker and frontend at the same revision, applying `alembic upgrade head`
through the existing deployment, which removes the previous worker before migration
and starts its replacement from the API image. Do not run old workers against new dedicated jobs.
No dependency, external account or environment flag is added. Review unresolved
provider receipts before any operational replay after rollback; database downgrade
alone is not proof of state-contract or external-effect reconciliation.

## Verification

See `delivery-4-verification.json` for final counts and commands. Coverage includes
SMS/WhatsApp continuations, accepted/failed/uncertain manual and automatic sends,
message arrival during takeover, control changes during interpretation, blocked
old workers/contexts, evidence and profile provenance, one closing per episode,
quiet hours/expiry/consent, virtual-clock delivery, migration/rollback, and actual
rendering of the operational context.

The monetary-dispatch fixtures now explicitly have active conversation/consent
preconditions; their original monetary assertions remain. A separate test verifies
that a paused conversation is blocked at the real dispatch boundary. The virtual
cadence test advances to the published due time rather than a fixed 25 hours.

All inference and provider calls in these local regressions are scripted/mocked.
PostgreSQL concurrency checks require a disposable `DIALOGUE_POSTGRES_TEST_URL`;
SQLite/scripted interleavings are not a substitute for real parallel PostgreSQL
writers. Live model, SMS/WhatsApp/Calendar and the complete business acceptance
matrix remain for SA-10. Existing Agent/Sales stylesheet budget warnings remain.

Overlay only the new/changed files from the differential ZIP at the repository
root on this base, reviewing any later overlapping changes.

```bash
git pull && git add . && git commit -m "Add durable human takeover, resume continuity and inactivity closings" && git push
```
