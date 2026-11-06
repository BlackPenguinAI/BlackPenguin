# Sales Agent — groups 1, 2 and 3

Base: `83706ec2382627a86b9c331ff781df6649577b66` (`main`).

## What this delivery changes

| Group | Implemented | Deliberately not activated |
| --- | --- | --- |
| 1: baseline and evaluation | Versioned acceptance matrix for all 27 PDF issues, fictional EN/ES fixtures, reproducible offline contract replay and regression checks. | No model-quality certification or production end-to-end run. |
| 2: state and evidence | Versioned scoped state, typed tasks/preferences/restrictions/offers, event snapshots, expected-revision writes, idempotent event keys and additive migration. | No live state backfill, automatic task transitions or migration of active conversations. |
| 3: understanding | Separate versioned interpretation prompt, strict JSON schema, independent/alternative/excluded requests, constraints, references and exact-message evidence; disabled internal preview. | No tools, CRM update, booking, sharing, handoff, outbound message, new public endpoint or admin UI. |

All live graph, worker, executor, delivery and rendering files are unchanged.
Registering the new models does not call the new interpreter. Even setting the
preview flag does not connect it to the live worker.

## Operational installation

1. Copy the differential repository files over the exact base, reviewing the diff if `main` advanced.
2. Use the existing deployment process, which must apply `alembic upgrade head`.
3. Confirm `alembic current`: expected new single head is `20261106_sales_dialogue`.
4. Keep `SALES_UNDERSTANDING_PREVIEW_ENABLED=false` (the code default). No prompt/model change is required in AI Settings.

The new migration creates only `sales_dialogue_states` and
`sales_dialogue_events`; no existing business record is updated or backfilled.
The predecessor is `20261104_inventory_confirmation`.
Prefer leaving this additive schema in place when rolling application code back.
An explicit migration downgrade **deletes the new evidence tables** and is not a
routine production rollback; archive them first if that is ever necessary.

## Contracts and boundaries

`sales-understanding/1.0` describes the current message, not an executable plan.
Every affirmative request belongs exactly once to `all_of` or an alternatives
group; exclusions cannot be requirements. An OR group is one acceptable option,
not an instruction to execute every branch. Arbitrarily nested Boolean logic,
ordered conditional fallback strategies and the execution planner are not
implemented here; uncertainty should be clarified rather than flattened into
an unsafe action.

Evidence for requests, alternatives, constraints, preferences and references
must be a nonempty exact substring of the current inbound message. This catches
fabricated/past-message citations but **cannot prove that a model understood a
negation correctly**. Model-backed adversarial evaluation is still required.
No model-supplied internal IDs, action lists or lead-facing replies are accepted
in this contract. Unknown fields, duplicate JSON keys, non-finite/boolean
confidence and invalid relationship members fail validation.

`Understanding.permits()` is only an interpretation check. It is **not** tool
authorization, consent or permission to perform business actions. A future
executor must additionally apply persistent restrictions, current published
facts, tenant permissions, verified resource availability and action consent.
Confidence is never treated as authorization or a calibrated probability.

`sales-dialogue/1.0` stores stable property/offer IDs, typed pending/suspended/
blocked/awaiting-user/completed/cancelled tasks and acyclic dependencies.
Saved selections and property/material offers are checked against their project
and active opportunity. Offer expiration must be timezone-aware. This delivery
stores but does not resolve references or execute expired offers. The next
groups must implement current-offer precedence, interruptions, resumptions,
explicit restriction reversals and tool-result transitions. An outdated or
foreign ID fails closed; it is not silently replaced with another property.

`sales-tool-result/1.0` is a future tool adapter contract distinguishing success,
empty, partial, revoked, denied, conflict, error and uncertainty. No adapter or
external tool execution is installed in these groups.

## Persistence and transaction semantics

The service scopes reads/writes by company, project, conversation and lead and
requires the active opportunity. Soft-deleted leads are rejected. Legacy
conversations read as revision 0/empty state **without any write**. State for
another project/lead is not implicitly copied. Outbound offer provenance and
preview history honor activation boundaries, with additional metadata checks.

Each successful write atomically stores a state revision and an event snapshot.
An expected-revision mismatch raises `DialogueConflict`; the caller must reload
and reconsider instead of overwriting a newer revision. Event keys are unique
within a conversation/lead. Retrying the same key/content/revision returns the
original state; changing its content or revision is a conflict. The service
does not commit: callers own commit/rollback. SQLite's legacy SAVEPOINT behavior
is handled so rollback also removes first-write events.

PostgreSQL uses row locking, a revision compare-and-swap and uniqueness
constraints for first-writer races. The included optional parallel-writer tests
need a disposable PostgreSQL database; local SQLite tests do not certify this
production concurrency behavior. A simultaneous first-write loser may need to
retry the same event key after `DialogueConflict` to obtain the winning result.

Events retain historical `state_after` and metadata even when the current state
changes. The service inserts only; ORM updates/deletes of event objects are
blocked. This is not a tamper-proof DB audit ledger: raw SQL and authorized
parent deletion cascades are not prevented. Existing retention/deletion policy
still applies. State contains lead evidence; treat it with the same privacy and
access controls as chat history. Diagnostics redact recognizable credentials,
tokens and private URL queries; do not put secrets into user preferences.

## Preview protocol

There is no HTTP endpoint for preview. It is an internal async function used by
tests/evaluation callers. A caller enabling it must supply an authorized `Scope`,
inbound message ID, expected revision, stable event key, and manage its session.
It rejects disabled/foreign/stale/invalid requests before inference. Production
credentials are not needed for the supplied offline harness.

When deliberately invoked with the flag enabled and without a fake `infer`, it
uses the existing OpenRouter adapter and can incur model usage charges; it does
not send SMS/WhatsApp. It reads the already-published global Sales configuration
without the legacy accessor's default-merging commits. Existing company/global
credential precedence is retained, and neither pack nor model is republished.
The separate structured-understanding prompt is versioned in code; editing it
from AI Settings belongs to the later configuration integration.

Model input includes scoped preceding history (up to 20 messages), approved
commercial context, persisted state and published Sales guidance as data. The
64 KB prompt limit fails before inference rather than silently dropping needs.
Provider/schema failures are recorded with safe error codes and do not replace
the last valid understanding. Accepted preview updates only `last_understanding`;
pending tasks, restrictions, preferences and business tables remain unchanged.
Retries reuse an existing committed outcome without a second inference. Two
concurrent previews can both incur inference before the write conflict; exactly-
once model charging is not claimed, and there are no external business actions.

Preview events include code commit, model, prompt/configuration snapshot,
strict schema, redacted model request, its original SHA-256, response excerpt
(16 KB), original response SHA-256/truncation flag, outcome and state revision.
The request hash refers to the original pre-redaction request; it need not match
the redacted export. Hidden model reasoning is neither requested nor stored.
New preview events are not yet integrated into the existing monitor exporter.

## Reproducible checks

From `backend`, using the repository's installed Python environment and ordinary
test configuration:

```bash
python -m pytest tests -q
python -m app.modules.sales_agent.understanding_evaluation --cases tests/fixtures/sales_understanding_cases.json --output /tmp/sales-understanding-offline.json
alembic heads
```

The offline replay is a **scripted-output contract test**, not a live LLM test.
It has no settings/database/provider dependency. The report explicitly marks
`model_quality_evaluated=false` and `external_actions=0`; it hashes the fixtures
and schema so subsequent model-backed runs can use the same cases.

To separately verify real parallel PostgreSQL writes on a disposable database
whose name ends in `_test`:

```bash
DIALOGUE_POSTGRES_TEST_URL='postgresql+psycopg2://USER:PASSWORD@HOST/blackpenguin_dialogue_test' python -m pytest tests/test_sales_dialogue_postgres.py -q
```

Do not use the production database for that test. Each case creates/removes
only its own random test schema. With no URL these two tests are explicitly
skipped, not reported as passing. Browser/live-provider behavior and deployment
are not exercised by offline tests.

Frontend regression suite (no frontend code changed):

```bash
node -e 'const fs=require("fs"),cp=require("child_process");const config="tsconfig.lossless-answers.spec.json";const includes=JSON.parse(fs.readFileSync(config)).include.filter(p=>p.endsWith(".spec.ts"));cp.execFileSync(process.execPath,["node_modules/@angular/cli/bin/ng.js","test","--no-watch","--ts-config",config,...includes.flatMap(p=>["--include",p])],{stdio:"inherit"});'
npm run build -- --configuration production
```

## Known remaining work

This delivery does not close the full new architecture or re-label all PDF
issues as fixed. Existing live-path probes for incorrect secondary appointment
labels despite explicit negation, and material selection despite a specific
exclusion, require future executor integration. The new interpretation
contracts can express and veto those cases but are not yet consulted live.

The next groups must add actual reference/task resolution, permissioned tools,
bounded reconsideration, complete response composition, configuration/monitor
integration, adversarial live-model benchmarking and staged rollout. Stakeholder
approval for extra multiple-choice cardinalities (issue 27) remains a separate
decision. The acceptance matrix preserves every original issue and makes these
boundaries explicit, so regression coverage is not confused with production
certification.
