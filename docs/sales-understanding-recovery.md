# Sales active flow: interpretation recovery

Base: 0e042f5602790c9e80a7072d8be5a3014bca57b6.
Apply this differential on top of that version (already contains consolidated onboarding).
Copy backend/ and docs/ over the repository; no files are removed. No database migration,
dependency, frontend change, model change or runtime/cohort activation is required.
Deployment/restart remains the operator's responsibility. Nothing was deployed or sent live.

## Observed failure

The supplied production evidence reports invalid_model_contract for a valid request about
available properties. The model combined inventory with the material-only unit_sheet subject,
invented an exclusion, and omitted the affirmative request from all_of/alternatives.
The active coordinator rejected it, then emitted a misleading safety clarification.

## Changes

- Bump the code-owned interpretation prompt to sales-understanding-prompt/1.2; explain
  material subjects, explicit exclusions, required request membership and a valid inventory example.
- Reject using identical evidence both to request and exclude the same topic/subject.
- In active mode, retry an invalid interpretation once, with validation feedback and the original
  current message/context. Do not execute invalid output, normalize away exclusions or drop constraints.
- Validate the corrected output with the full schema, relationships and exact evidence rules.
- Bound active inference to 20 seconds per attempt (maximum two), under the existing 45-second
  coordinator limit. Provider failures do not trigger this repair. Preview remains single-attempt.
- Preserve attempt outcomes, bounded raw outputs, validation issues and repair feedback in the
  existing scoped audit event. Do not put input values or Pydantic contexts in validation feedback.
- On unrecovered failure, acknowledge a processing problem rather than label the lead's request unsafe.
- Preserve the actual model/prompt and useful run error code on the failure path instead of model=pending.
- Keep existing consent, tenant scope, manual takeover, asset approval, booking and delivery guards.

This is not a general rewrite of the Sales AI, a permissions expansion, or an audit of all
qualification/compliance behavior. It addresses the demonstrated interpretation failure and recovery.
Do not replay old failed jobs to test it: durable receipts deliberately prevent duplicate replies.
Historical fallback messages are not rewritten or automatically resent.

## Verification

Offline tests inject model outputs and mock outbound sends; no OpenRouter, Telnyx, Meta or
Calendar calls were made. The new regression suite covers the supplied malformed output,
successful inventory recovery, bounded failures, provider errors, contradictory evidence,
manual takeover during repair and durable retry without duplicate sends.
Full backend suite: **1445 passed, 2 skipped**. git diff --check passed.
The full backend test result is included in delivery/backend-tests.log.
No frontend changes were made, so no new frontend build or browser acceptance is claimed.

## Operator acceptance after deployment

1. Confirm the deployed image includes this patch. Runtime flags and selected cohort stay unchanged.
2. With an explicitly consented test lead, send one new available-properties inquiry.
3. Expect a grounded catalog reply when approved inventory exists, or a specific missing-information
   response if not. Never invent availability or force booking/material delivery.
4. Inspect the new understanding_preview metadata: prompt_snapshot.version should be
   sales-understanding-prompt/1.2; outcome accepted; interpretation_attempts length one or two.
5. If both interpretations fail, retain the recorded validation_issues for diagnosis; the lead
   should receive the processing-error fallback, with no unrequested business effects.

Real-model response quality and live messaging acceptance remain to be verified in your environment.
Adding this patch does not prove every possible conversation works correctly.
