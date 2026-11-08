# Sales conversation continuity and administrator review

This differential is based on main commit `d905c635d594c18c5e3dae830594a02fc0bb4dfb` and includes
the preceding `BlackPenguin_sales_active_e2e_differentials.zip` changes. Apply this delivery instead
of that ZIP, not before it. No database migration or new runtime dependency is required.

## Behavior

- An invalid interpretation gets the existing bounded repair attempt. If repair fails, a processing
  reply is recorded and sent without pausing the conversation. The next new inbound can succeed.
- Low confidence, unclear references and missing approved information/materials require clarification
  or a Sales notice. Stored legacy `pause_on_*` flags cannot pause these ordinary situations, and
  their ignored values remain visible in the escalation trace. Published settings are not rewritten.
- A model's `human`, `opt_out`, `security_or_abuse`, `requires_human` or review action is insufficient
  to pause a chat. Current affirmative evidence or explicit confirmation of a server-issued handoff
  question is required. Mentions, negations and reported requests are not automatic control consent.
- Actual STOP/unsubscribe requests remain effective, including while already under manual control.
  Requests limited to particular materials/offers must not silently unsubscribe all messaging.
- Explicit human takeover, concrete unauthorized-access requests and validated tenant/demo violations
  retain intervention controls. Appointment-confirmed closure is unchanged.
- Legal/commercial exceptions can require staff approval of the requested action while the chat
  remains active. They do not authorize new legal advice, discounts, files or bookings.

## Approved compliance guidance

The presence of Company or Project compliance notes no longer creates `PROJECT_COMPLIANCE_REVIEW`
and pauses every first interaction. Instead, read tools and material/appointment executors hold
affected commercial actions and create a non-pausing Sales notice with reason `ACTION_POLICY_REVIEW`.
Other approved information remains available. Company and Project restrictions accumulate.

This is deliberately not an arbitrary natural-language policy compiler. A complete note of the form
`Human approval required for financing claims` (or the corresponding pricing/materials/appointment/
location/delivery/inventory action) supplies a narrow action scope. Unrecognized free-text notes keep
the conservative commercial-action hold until staff review/clarify the approved guidance. Chat
clarification stays available; permissions are never inferred from ambiguous policy text.
Pricing/inventory holds also cover catalog/detail payloads that could contain those facts.
Prepared sends re-check newly approved action restrictions before dispatch.
Proactive cadence remains suppressed while custom guidance awaits review.

## Administrator workflow

The Agent screen shows a prominent pause review card with its reason, rule code, timestamp and
the triggering message. The conversation thread provides context. Administrators/assistants can:

1. Reply manually using the existing composer while the AI remains paused. The original incident
   reason is preserved after the reply.
2. Resume the AI with an optional review note.
3. Enter a required explanation and choose **False positive · resume AI**.

Resolution records the reviewing user, time, case IDs and note in the existing immutable platform
audit stream. The case history remains visible after resuming. False positives suppress only the
same normalized reason/message trigger within that conversation and lead; they do not waive
tenant permissions, approved action restrictions, opt-out or a new distinct incident.
A renewed handoff can be confirmed explicitly after the AI asks its transfer question.

The action API accepts `review_case_id`, `false_positive` and `review_note` with `action: resume`.
A stale case ID returns 409; Sales cannot review/resolve false positives. Access remains Company
and Project scoped. An opted-out lead or an appointment-confirmed closure cannot be resumed here.
Closing a case releases its open-incident uniqueness key, so later genuine incidents can be recorded.

The summary API adds `intervention_cases`, `processing_issue`, `review_notice` and `can_resume`.
Old paused conversations require explicit staff review; this delivery does not automatically resume
them. Resuming never rewrites history, replays failed jobs or resends old messages.

## Verification and rollout

See `delivery/manifest.json` and the included logs for the current test results. Coverage includes
both SMS and WhatsApp coordinator/dispatcher paths, a subsequent successful turn after bad
interpretations, high-confidence false handoff/opt-out labels, explicit handoff confirmation,
scoped compliance holds, manual reply, review API authorization, audited resolution, stale-case
rejection, STOP, case reopening and duplicate-delivery regressions.
Models and outbound providers are mocked; real network contacts were not messaged.

Build and deploy the backend and frontend together. The active runtime feature flag and selected
Company/Project cohort still need to be enabled in the deployment's existing configuration; this
patch does not activate or expand a cohort. Shared legacy escalation also follows continuity rules.

After deployment, use an expressly authorized test lead and **new inbound messages** to repeat Mau's
first SMS and WhatsApp interactions and Jorge's reported WhatsApp request with the real configured
model. Verify replies, uninterrupted subsequent turns, and the absence of spurious pause cases in
`/monitor`. Exercise an explicit handoff, a manual staff reply, false-positive resolution and another
new turn. Check STOP separately. Real-model interpretation quality and live provider acceptance
are not established by offline test results or by merely applying this ZIP.
