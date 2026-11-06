# Sales Agent: staged groups 4, 5 and 6

Base: 6ddbbbbbd3e121465fa8beecd4c23a1613be86c5. Requires groups 1–3.
This delivery does not activate live conversations or replace their executor.

## Group 4 — references and tasks

The new reference resolver uses scoped, actually recorded outbound offers and
their original ordered identifiers, not current catalog sorting. Numeric and
ordinal references use the existing bounded choice parser; exact property names
are checked against the approved catalog. Multiple kinds offered in the same
message, absent/expired offers and unsupported expressions require clarification.
A typed reference can select the latest matching kind; an untyped reference
cannot arbitrarily choose between property and appointment offers.

Task IDs include their originating message, preventing a model's repeated local
request identifier from overwriting an earlier turn. Tasks preserve dependencies,
interruption state, subject and alternative group. Explicit preferences update
the same preference key; older evidence remains in event snapshots. Turn-only
restrictions expire next turn, persistent restrictions do not silently disappear.
The current understanding contract has no explicit restriction-release command:
a new conflicting affirmative request stays blocked until a later explicit,
validated release workflow is implemented. Do not infer reversal from confidence.

The optional task fields are JSON additions, not new SQL columns. Current code
reads legacy tasks with defaults. Old strict readers may reject populated new
fields if rolled back after enabling this internal runtime; keep feature gates
off during mixed-version deployment and retain evidence instead of rewriting it.

## Group 5 — typed read tools and effects boundary

ToolCall rejects unknown fields and binds operation ID, task, topic, subject and
optional selected property. Each lookup rechecks the active company/project/
lead scope, task status, explicit restrictions and the approved commercial
context. That context retains existing published-version, money provenance,
inventory freshness, asset expiry/channel permissions and safe-link policies.

Available reads: catalog, selected property details, pricing, inventory, approved
project facts (financing, delivery, amenities, location) and approved materials.
Missing fields return empty, not invented facts. Catalog results are partial
coverage, not a denial that other properties exist. Materials disclose matching
content tags, file metadata and only relevant safe embedded links. A brochure
offered as a possible photo alternative is partial/unverified photo coverage,
not proof of extracted photographs. Matching general brochures and separate
files are retained; there is no all-requested-tags-in-one-file requirement.

The per-turn operation ledger rejects reuse of an operation ID with different
arguments. Read retries revalidate rather than replay a revoked asset's stale
metadata. Committed whole-turn retries use the saved event outcome; this is an
audit replay, not fresh sharing authorization.
Returned runtime outcomes are diagnostic proposals and are sanitized on both
first call and replay. Private URL queries are redacted; future dispatch must
use asset IDs to revalidate and obtain fresh delivery links, never send a
redacted diagnostic URL to a lead.

Appointment booking, human handoff, opt-out mutations, CRM updates and document
sending are explicitly denied here. There is no outbound action adapter, consent
UI, reservation transaction or provider idempotency implementation in this
delivery: those effects must remain disabled until integrated and tested.
It would be incorrect to claim exactly-once provider delivery from a read ledger.

## Group 6 — bounded reconsideration

run_turn consumes a validated structured understanding of a real scoped inbound
message. The group-3 interpreter can supply this contract; this function does
not call an LLM itself or add a second autonomous agent. It prepares tasks,
resolves references, executes one eligible read, observes its typed result, then
reconsiders eligible tasks. An empty OR branch allows the next branch; a usable
branch cancels unused alternatives. Independent requests continue separately.
Clarification holds interrupted tasks; dependency and time/step limits preserve
pending needs instead of dropping them.

Tool statuses drive transitions: success/partial lookup completion, empty/
denied/revoked/conflict blocked, errors suspended, uncertainty awaiting user.
Material discovery is an exception: the task remains pending because no file
was sent. A partial lookup result does not assert full catalog coverage or user
delivery. The later response composer/dispatcher must fulfill the request.

Defaults: 8 steps, 5 seconds; bounded configuration allows at most 30 steps and
30 seconds. Time limits are cooperative checks between synchronous tool calls,
not a hard timeout capable of interrupting a database call. Each task is attempted
at most once in a turn; an error cannot cause an endless retry loop. Large
contexts still obey the existing event-size limit; no result is silently
truncated into a misleading complete answer.

State and event are saved together using group-2 compare-and-swap. Callers own
commit/rollback. A stable event key plus input fingerprint returns the committed
result without repeating tools; changed inputs conflict. Scoped event metadata
includes reference decisions, typed tool results, stop reason and zero external
actions. The existing store redacts diagnostics and preserves event history.
No new HTTP endpoint or monitor route is added.

## Installation

Copy the differential backend/ and docs/ files over the base. No additional
migration is required beyond group 1–3 head 20261106_sales_dialogue.
Keep both settings false:

- SALES_UNDERSTANDING_PREVIEW_ENABLED=false
- SALES_DIALOGUE_RUNTIME_ENABLED=false

The live graph, worker, provider dispatch and frontend are unchanged. Setting the
runtime flag alone still does not attach it to live processing. It is an
internal evaluation entry point; callers must enforce their own authenticated
authorization before supplying a Scope. Do not expose it as a public endpoint.

## Tests and limits

Run from backend with the ordinary repository test configuration:

    python -m pytest tests/test_sales_runtime_456.py -q
    python -m pytest tests -q

The 22 scripted understanding scenarios from group 1 are replayed through the
runtime alongside dedicated transition, OR fallback, revocation, retry,
expiration, ordering, dependency, limit and non-effect tests. These are offline
contract/state tests, not natural-language model accuracy benchmarks.

The frontend regression/build commands remain in sales-agent-groups-1-3.md.
Two inherited PostgreSQL parallel-writer tests need a disposable database and
are skipped without it. No live model, SMS/WhatsApp, OAuth or production mutation
is part of this validation. Response composition, live integration, explicit
restriction release and real effect adapters remain later work. In particular,
this delivery does not yet fix observed live chat responses by turning on a
new engine.
