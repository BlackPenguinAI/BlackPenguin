# Delivery 1 — Current Sales workflow and evidence recovery

Base: `aac1fa6d263cb91019e6191349321af0aefeaa27`.
Scope: SA-01 and SA-02. This delivery is not acceptance of all 64 business scenarios.

## Result

The deployed Sales coordinator handles every eligible existing and new Company,
Project and lead. Production inbound and follow-up entry points never fall back
to the historical graph. No onboarding repetition or per-Project activation is
required. Existing global model configuration remains necessary for inference;
unconfigured/ambiguous configuration does not authorize commercial effects.
STOP remains independent of whether a model is configured.

`SALES_DIALOGUE_RUNTIME_ENABLED`, `SALES_NEXT_FLOW_ENABLED`,
`SALES_NEXT_FLOW_PROJECT_IDS` and historical runtime mode/scope/ID filters no
longer select the production engine. Old environment values can remain false or
empty: changing them is unnecessary. Execution limits remain validated.
Historical published configurations and audit records are not overwritten.

Consent, opt-out, human pause, approved Project capabilities, Company/Project/lead
scope and approved resources still govern actions. Exact platform-generated
standard compliance choices mean no additional Project restriction; arbitrary
custom notes are not interpreted as permission to waive restrictions. Existing
reviewed rules still apply, including when a note changes.

AI Settings removes engine rollout/cohort and ineffective legacy classifier
switches. The Sales protocol editor now edits the business playbook, not the
historical reply JSON schema. Intent examples/instructions are reference data for
the current interpreter; they cannot alter platform contracts. Draft/publish and
commercial customization remain available. The mirror separates current workflow,
last recorded turn, configuration, Project and inbound processing results in rows.
An older recorded turn is not relabeled as a current-flow run.

## Interpretation

The current internal interpretation prompt is `sales-understanding-prompt/2.8`.
Evidence failures identify the exact field path. Evidence must quote the current
message, even when spelling or grammar is imperfect. Normalized meaning belongs
in value/expression fields, not in a fabricated quotation.

Only a unique reversible case/space/typographic-quote match can recover the
original quotation. No fuzzy matching, spelling correction, borrowed history,
word removal or substitution of the whole message is used to authorize actions.
Ambiguous format matches remain invalid. Model output is still validated after
anchoring, including contradictory requests/exclusions and reference integrity.

One bounded repair receives field-specific feedback and the original message.
Repeated failures retain an observable error, notify administrators once per
failure episode and avoid repeatedly sending the same fallback. The conversation
is not paused or classified as hostile because inference failed. Recovery on a
new valid interpretation remains possible. No automatic bulk retry of old
conversations occurs at deployment.

The English input gate admits ordinary conversational language and short English
context containing a couple of new words/typos, while retaining the explicit
non-English-clause check and English-only automatic output validation. Language
detection never grants consent or action permission.

## Shared simulator and effects

The simulator uses the same current coordinator, interpreter, planner, tools and
composer. Task-local adapters supply its virtual clock and in-app delivery.
Simulation consent is scoped to a dedicated simulation conversation; it cannot
authorize real SMS or WhatsApp. Simulated receipts identify in-app-only delivery.

Simulated bookings are Demo meetings and do not create/update/delete Calendar events or contact the real
messaging provider, hold live appointment capacity or advance live round-robin.
Simulation notifications cannot reach the real staff notification worker.
Simulation and live appointment reads/mutations are isolated. A failed model
response or a paused conversation cannot silently re-enable human control.
The existing explicit Calendar-test button remains an explicit, separately
authorized operation; it is not executed by the chat adapter.

Private historical graph helpers remain solely for compatibility unit tests.
No production router, worker, AI Settings value or environment selector invokes
them. Historical proposal-schema tests explicitly name these helpers; current
coordinator tests and the new simulator tests exercise the deployed path.

## Pending effects and compatibility

Already-completed events are not replayed. An unfinished event belonging to a
historical engine is blocked for reconciliation, preserving its snapshots and
receipts instead of reinterpreting it under another engine. Existing current
prepared replies reuse their durable effects/receipts and revalidate delivery.

Calendar, replacement, cancellation and wait workers no longer filter by rollout
lists. Each operation retains its own scope/authorization checks. Malformed
historical Calendar receipts are placed in review without stopping another
scope's recovery. Workers never create a new reservation to recover a Calendar
effect. Demo meetings cannot trigger real Calendar recovery.

## Applying the differential ZIP

1. Update the repository from main. The package was prepared against the base
   above; if main changed, review overlapping files before copying.
2. Copy the ZIP's `backend`, `frontend`, `docs` and `VERIFICATION` directories over
   the repository root. They contain only new or changed files.
3. No new dependency or Alembic migration is introduced. The existing Sales
   schema must already be installed; the confirmed production head was
   `20261108_sales_moderation`. Readiness now checks required Sales columns too.
4. Review the differential and use the commit command below. The repository's
   existing workflow performs deployment after push.

```bash
git pull && git add . && git commit -m "Make the current sales workflow mandatory and fix evidence validation" && git push
```

Do not run `init_db` to republish prompts, clear state, reset jobs, replay old
messages or remove pauses. This package does none of those operations.

## Verification after deployment

- Confirm matching API/worker/frontend image revisions and successful readiness.
- On an authorized test conversation, verify the mirror shows the current
  workflow and that a NEW turn records prompt 2.8; historical turns keep their
  historical provenance.
- Exercise the five reported catalog/inventory phrases, spelling errors and
  punctuation-free requests. Check the persisted response and the phone receipt.
- Verify a new Project inherits the workflow without editing IDs or flags.
- Verify pause and STOP still prevent prohibited contact; Demo uses only the
  in-app simulator.
- Review processing/configuration/action-policy issues shown by the mirror.
  A custom restriction requiring review is not a missing engine activation.

These checks use new authorized test events. Do not resend the historical failed
messages to real leads as a deployment verification.

## Validation boundaries

See `VERIFICATION/sales-delivery-1.json` for completed automated results.
Automated tests use isolated databases, scripted inference and mocked external
providers. Passing them does not prove live-model quality, receipt on a phone,
real Calendar effects or PostgreSQL concurrency. Existing PostgreSQL-only skips
remain explicitly reported. Live acceptance is part of the later SA-10 closure.
Pre-existing frontend style-budget warnings remain documented.
