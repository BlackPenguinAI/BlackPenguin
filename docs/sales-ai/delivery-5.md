# Delivery 5 — Sales safety, runtime health and acceptance evidence

Base: `5064006f8f98d430aaed2b9ec298d9a17b0c47ea` (Delivery 4 on main).
Scope: SA-09 and the SA-10 implementation/verification tooling. The changes in
this differential have not been deployed by this work. Production/model/channel
acceptance is **pending**, not inferred from scripted regression results.

## SA-09

Moderation now accepts evidenced semantic personal harassment, including phrasing
outside the literal insult list. An exact current quote, high confidence and a
directed target are required. Commercial criticism, ordinary frustration,
reported/quoted language and negated abuse do not become personal harassment.
A respectful return to property questions continues the conversation. A negation
in a separate clause does not hide a concrete independent attack.

Requests to execute code or browse unrelated material receive a scope warning.
Repeating that behavior after an accepted warning creates an audited intervention
and pauses automation. Approved Project websites/materials are not classified as
unrelated browsing. Personal abuse similarly requires an accepted prior warning
within the existing 24-hour window before a repeated-abuse pause. A failed or
unaccepted warning is not evidence that the lead ignored it. Concrete threats and
private-data/credential extraction retain immediate protected handling.

The interpreter advances to `sales-understanding-prompt/2.12`. The moderation
contract gains `unauthorized_use`; no tool-execution permission is added. Existing
incident review/false-positive resolution, tenant boundaries and consent remain
in force. The application persists intervention evidence before claiming it was
recorded. No model or customer instruction can enable an unapproved action.

Transport failures that leave provider acceptance uncertain (including wrapped
HTTP 5xx/network errors and missing message identifiers) create a durable
`delivery_unknown` receipt and reviewable work. Automatic retries do not submit
that outbound again. Definitive rejection/local preflight failures retain their
existing bounded retry behavior. Partial-message delivery retains stable part
keys. This does not claim that an external provider offers exactly-once delivery;
unknown receipts need reconciliation. The mirror explicitly explains the unknown
state and that automatic resend has stopped.

The final live dispatch boundary also rechecks current-engine authorization and
contact consent for proactive work. Existing verified booking/replacement/
cancellation, scope, lease, idempotency and material services remain authoritative.

## SA-10: real Sales queue health

The Sales queue loop runs in the **API process**. The separately deployed
`bp_worker_prod` process handles onboarding; its heartbeat cannot prove Sales is
working.

New `sales_worker_progress` rows record successful inbound/follow-up claim scans,
Calendar retries, availability waits and operational-outbox scans. Job completions
are counted separately from successful idle scans. There is no independent timer
that can make a stalled queue appear healthy. Scheduled-claim errors are exposed
and no longer terminate the loop permanently.

`GET /api/v1/health/sales` first checks the required schema, then checks this API
instance's revision, scan freshness, stopped/error state and actual loop progress.
It also flags review/failed jobs and overdue work. It exposes no lead/customer IDs,
message bodies, credentials or tenant configuration. Only the exact read-only
health URL is public; nested paths and mutations remain protected.

A healthy queue scan does **not** prove a model understood the lead, a provider
accepted a message, or a device received it. Attention/overdue indicators remain
separate from process readiness.

The deployment now writes a candidate-image-bound 64-case scripted report with
network disabled and runs the isolated PostgreSQL races before stopping production
containers. It checks Sales health alongside schema readiness and again after
the stability window. It already removes old containers before migration and
starts API/onboarding worker from the same image. Preflight mounts the candidate
workflow read-only so the deployment regression actually checks that file.

Migration: `20261109_sales_worker_progress`, after
`20261109_sales_continuity`. It adds the progress table/index only. No production
dependency or environment toggle is added; existing Company/Project onboarding
and current-workflow selection are unchanged. The release audit remains SELECT-only
and distinguishes effective mandatory/global runtime from inert historical
rollout settings. Release evidence checks now require the current migration head,
64-case registry, Sales queue progress and inactivity evidence as well.

## Executable 64-case registry

`backend/tests/fixtures/sales_ai/current_acceptance64.json` preserves the 64 agreed
IDs/titles and maps deterministic cases to executable semantic/effect assertions.
Its paraphrase fixtures include the observed imperfect-English/property requests;
these are test examples, not an exact-phrase production router.

Run from `backend/` with the application's normal test dependencies/configuration:

```bash
python -m tools.sales_ai.current_acceptance --mode regression --output /tmp/sales-acceptance64.json
```

The runner records actual pytest node outcomes, including every collected
parameter variant and setup/teardown/collection failures. It never marks an
unexecuted reference passed. It hashes the fixture and test sources. Each scenario
has separate scripted-regression, real-model and SMS/WhatsApp results; a local
scripted PASS cannot silently turn into real business acceptance.

See `delivery-5-acceptance64.json` and `delivery-5-acceptance.md` for the executed
local result. Case 57 (real-model/end-to-end quality) remains `NOT_RUN`. The report
of the bounded real-model evaluator records missing credentials, zero model calls
and no claimed model-quality result.

## Remaining external validation and commands

The local environment refused AF_UNIX socket creation when starting a disposable
PostgreSQL instance. No production database was used as a substitute. Seven real
PostgreSQL tests are included: four existing reservation/state races plus three
new duplicate-Resume, inbound-vs-Resume and FIFO races. They are not counted as
executed here.

On a Docker-capable host, use the candidate repository checkout and image after
building the same commit. The following helper creates a new internal Docker
network and PostgreSQL 16 test database, mounts only test sources read-only, uses
synthetic credentials, disables outbound access and cleans up its own containers/
network. It never loads the production `.env`, database or volumes. Its image
revision check rejects a different candidate; all seven tests must run without
skips for PASS.

```bash
# From the candidate repository's backend directory:
python -m tools.sales_ai.postgres_checks \
  --image "$(docker inspect --format '{{.Config.Image}}' bp_api_prod)" \
  --expected-commit "$(git rev-parse HEAD)" \
  --output /tmp/sales-postgres-checks.json
```

For a bounded real-model rehearsal, provide a reviewed, credential-free published
Sales pack and offline catalog. Set `OPENROUTER_API_KEY` through the host/container's
secret handling, never in a commit or a pasted command. The existing evaluator
uses mocked messaging/Calendar and a bounded inference subprocess:

```bash
python -m tools.sales_ai.evaluate_model --mode real \
  --agent-pack /secure/reviewed-sales-pack.json \
  --catalog /secure/offline-catalog.json \
  --repeats 2 --max-calls 100 --budget-usd 2 \
  --output /tmp/sales-model-evaluation.json
```

These model probes are narrower than full 64-scenario live acceptance. Actual
SMS/WhatsApp and Calendar checks require authorized test contacts, scoped test
Company/Project data and independent verification of provider/device/Calendar
receipts. No such real messages or Calendar actions were performed here. The
release checklist validates local evidence integrity; it never grants deployment
or provider-contact authorization by itself.

## Applying and rollback

Overlay the ZIP's new/changed files at the repository root on the stated base,
reviewing later overlapping changes. Include the migration, workflow, source,
tests, fixtures and verification documents. Run `alembic upgrade head` through
the existing deployment with API/worker/frontend at the same release.

Preserve approvals, pauses, opt-out, reservations and unknown provider receipts
when recovering from a release issue. Prefer a corrected compatible artifact.
New moderation enum values can be present in JSON audit/state: an older strict
reader is not automatically compatible. A schema downgrade alone is not a safe
rollback of model contracts or external effects; do not reactivate the legacy
engine or blindly resend unknown operations.

See `delivery-5-verification.json` for final regression/build counts and limits.
Existing Agent/Sales stylesheet budget warnings remain. PostgreSQL/real model/
real channel acceptance stays explicitly pending until its separate evidence is
observed and reviewed.

```bash
git pull && git add . && git commit -m "Harden sales effects and add runtime health and acceptance checks" && git push
```
