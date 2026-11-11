# Delivery 3 — respectful closures and durable human-contact requests

Base: b672f9e9e509863dc015e183d9a66cae1b4dd8f3.
Published Sales model/configuration remains unchanged. Prompt version is 2.21.
No schema migration is required.

## Lead-facing behavior

1. An explicit first human-contact request receives one offer to help with the
   question. A mixed property question still uses the normal interpreter/tools and
   is answered before the single closing question. Pure requests need no model.
2. A repeated verified request after an accepted help prompt creates a durable
   pending request. The reply confirms it was saved, asks whether there is another
   property question and offers a polite conditional goodbye. No assignment,
   transfer, callback or deadline is promised.
3. A pending request does not stop inbound AI answers. Automated sales cadence and
   inactivity follow-ups stop after insistence; existing meetings and appointment
   reminders are not cancelled. The request alone does not create a visit.
4. The lead can explicitly cancel the human-contact request. Its historical case
   remains cancelled; a new request can create a new pending case later.
5. Declining a visit leads to an offer to answer another property question. A clear
   standalone goodbye/no-more-questions outside an active booking/change confirmation
   is handled without a model and introduces
   no new question, opt-out or meeting mutation. Existing booking/cancellation/
   rescheduling confirmations retain their established handling. A later question
   remains answerable.
6. When an availability alert is declined, the reply can offer other property help
   rather than pressing the lead to return to booking. Existing alert functionality
   and opt-in requirements are unchanged.

## Persistence and control

The existing HumanInterventionCase review queue stores a distinct reason,
HUMAN_CONTACT_REQUEST. The record binds company, project, conversation and lead.
It records the current insistence evidence, remains visible in conversation history
and does not set human_control, pause the conversation or change the sales stage.
The frontend labels it "Human contact requested" and excludes it from pause-review
controls. Actual human takeover and security incidents retain their existing rules.

The first help prompt must be provider-accepted before a later request is counted
as insistence. A failed/undelivered prompt is not used as authorization. Continuity
lead/project/epoch boundaries invalidate prior prompt context. Case creation and
its receipt participate in the prepared turn; retries reuse the scoped open case.
Cancelled/resolved historical records retain their identity and release the open
request deduplication key. Platform events record ask/record/withdraw operations.

This is storage of a pending contact request, not proof that a human has contacted
the lead. It sends no automatic staff email/SMS or callback. Staff can see the
request in the existing conversation review history. Fulfilment/assignment and
contact SLA are separate work.

Opt-out, staff pause/manual control and credential/security restrictions take
precedence. A model label alone cannot register a human-contact request. Mixed
questions that fail interpretation still retain the verified contact request via
an audited deterministic fallback; no internal model error is narrated to the lead.

## Silence and evaluation boundaries

No new silence interval, repeated prompt or notification scheduler is introduced.
The existing configured inactivity behavior remains unchanged for other exchanges;
terminal conversations and recorded human requests suppress that cadence. The new
"any other question?" is sent as part of the current reply, not as a newly scheduled
proactive message. A dedicated silence-question interval/limit remains undecided.

The new closing-point suite has eight short scripted dialogues (25 lead messages):
visit refusal with a financing question, human request followed by a question,
insistence, question after recording, withdrawal, farewell then reopening,
unavailability then closing, and a mixed human/price request. It uses the same
private synthetic company/projects and current coordinator. Human-contact records,
post-commit profiles, queue visibility, no unwanted meetings, no callback promises
and cadence behavior are checked. No real lead contacts or production writes occur.
No active Sales roster is seeded during evaluated closing cases, so the availability
case observes a lack of eligible sellers. Actual transport, Google Calendar,
notification delivery and every buyer segment remain outside this focused suite.

Offline tests include SMS/WhatsApp boundaries, a model outage, failed prompt delivery,
retry deduplication, repeated requests after cancellation, cross-company case isolation,
security/manual-control precedence, genuine mixed questions and staff rendering.
Final validation: 2,721 backend tests passed, 7 skipped, 0 failed; 121 modules
covered exactly once. Sales acceptance: 63 PASS, 0 FAIL, 1 NOT_RUN (live acceptance
pending). Frontend: 532 tests passed and production build passed. Local fake-provider tests do
not replace the post-deployment evaluation of the published model.

## Apply and run

Extract the differential ZIP over a checkout at the base or a compatible newer commit.

```bash
git pull && git add . && git commit -m "Add durable human contact requests and respectful sales conversation closures" && git push
```

After successful deployment, run in the server SSH console with a new output path:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite closing-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 96 --max-turns 4 \
  --output /tmp/sales-closing-point-1
```

96 is a call cap, not a dollar cap. Deterministic contact/terminal controls need
no Sales inference; factual questions still use the published model. Actual provider
usage and cost are exported. Exit status 2 still exports diagnostic failures; copy
in a separate command even when the evaluation reports FAIL/INCOMPLETE:

```bash
docker cp bp_api_prod:/tmp/sales-closing-point-1/synthetic-sales-results.zip ~/sales-closing-point-1.zip
```

Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-closing-point-1.zip "$env:USERPROFILE\Downloads\sales-closing-point-1.zip"
```
