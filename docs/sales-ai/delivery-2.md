# Delivery 2 — Lead profile, memory and property comparisons

Base commit: `77e3a1d7937cbff712ad7493650b30af0008d1cd` (Delivery 1).
Scope: SA-03 and SA-04. This is not acceptance of all 64 scenarios or the later
resource, flexible prose, human takeover and inactivity deliveries.

## Behavior

The mandatory current workflow remains the production entry point for existing
and new Companies, Projects and eligible leads. No per-Project activation,
onboarding repetition or staff switch is added. The internal understanding prompt
advances to `sales-understanding-prompt/2.9`; published business playbooks remain
reference data. No republishing is needed to apply this backend contract.

### SA-03

- Commercial answers from Meta's flat and Graph field shapes, source answers and
  existing evidence-backed profiles remain available with their source, status
  and evidence. Manual leads can start with no profile facts.
- Volunteered age and occupation have a separate `optional_profile` namespace.
  Current values, corrections, refusal and withdrawal retain provenance. The
  agent must not ask for either field, infer other personal traits or turn an
  occupation into an assumed budget, requirement or ability to finance a home.
- Explicit functional needs, bathrooms, motivation and decision structure join
  the commercial preference vocabulary. The original quote is the authoritative
  stored value; model-normalized personal values are not written.
- A refusal can be expressed in different ways and is interpreted as `declined`.
  Known, declined and withdrawn qualification fields are not asked again.
  Removing a budget suppresses its min/max/currency aliases too. Tombstones keep
  old Meta/compatibility facts from silently restoring a withdrawn value.
- Corrections supersede the current record with a link to the previous version.
  Withdrawal stops use as a current profile fact; it is not an erasure of the
  conversation, source form or historical audit records and is not contact opt-out.
- Current interest, restrictions, qualifications and pending comparison criteria
  and references remain in durable scoped state, independently of booked visits.
- Scoring now reads current commercial facts and actual inbound engagement,
  rather than searching the entire conversation, profile JSON or summary for
  keywords. Negated, declined, unknown and withdrawn facts do not produce positive
  readiness signals. Age and occupation are not scoring inputs. Budget fit needs
  an explicit cap/currency and a comparable approved price for the selected option.
  A source declaration is not a credit check, confirmed funding or housing eligibility.
- Published Company/global scoring weights apply; draft edits do not change live
  scores. Score updates do not advance or overwrite the operational workflow stage.
- Segment selection uses the finite semantic purpose chosen by interpretation
  from an explicit buying-purpose declaration, with the original quote retained.
  There is no history-wide keyword/persona classifier. A canonical source form
  choice can be used directly. A free-text source answer can be classified only
  against the hash of its exact current buyer_type/motivation record; a correction
  or withdrawal invalidates the old annotation. Unknown or conflicting purposes
  stay unsegmented. Old inferred personas do not select published guidance.
- Objections use typed, current-message evidence for price, timing, comparison,
  trust or approval, with explicit raise/resolve. Neutral comparisons and price
  questions are not automatically objections. Replays do not increment the same
  objection twice. Objection records select guidance without pausing the agent,
  forcing a stage or using the historical keyword-based stage updater.

### SA-04

- A typed comparison links one catalog read to named/ordinal references, current
  focus, all typologies or actual individual units. Other requests in the same
  message retain their own tasks and results.
- Replies compare the requested characteristics: bedrooms, bathrooms, area,
  price, last confirmed quantity, kitchen details or approved features. A specific
  requested feature is filtered before truncating unrelated feature lists.
- Maximum/minimum use numeric approved values and report ties. Missing values
  are not zero. Mixed currencies, unconfirmed dimensions, non-exact price/area
  ranges or restricted values cannot produce a definitive ranking. Compatible
  square feet/metre dimensions can be normalized for ranking; original units are
  shown. Individual inventory units have no area-unit column in the current
  schema, so their dimension is explicitly unconfirmed rather than inherited.
- Kitchen statements come from approved features or approved description text.
  Missing confirmation is not a claim that an option lacks a feature. General
  comparisons do not invent a subjective best option or financial performance.
- The comparison tool reapplies Company/Project/lead scope, approved catalog
  membership, global policy holds and per-property/unit restrictions. It returns
  grounded comparison wording rather than exposing an unrestricted raw catalog.
  The existing post-composition catalog revalidation remains in force.
- Merely comparing with another option does not select it. An explicit choice
  can change current commercial focus, and never changes an existing meeting.
- Displayed offer IDs preserve the actual displayed order. Large comparisons
  show at most 12 options with explicit coverage; numeric extrema examine all
  supplied comparable records, including options beyond the displayed subset.
- An unresolved comparison stays pending with its criteria/references. It does
  not silently become a normal catalog read on a subsequent unrelated turn.
  A fresh clarification is interpreted against that pending context.
- Text details, digital materials and explicit physical visits retain separate
  intents and permissions. This delivery does not alter file delivery contracts.

## Implementation and compatibility

The changes are additive to existing JSON profile/state storage. No dependency,
SQL column, Alembic revision or environment variable is added. Old state can be
read using defaults. API and worker must run the same new revision; an older
binary with a strict schema cannot be assumed to understand newly written JSON
fields. A code rollback is therefore not a promise of backwards-readable state.

Historical private compatibility helpers stay out of production selection.
AI Settings, the mirror layout, consent, pause, opt-out, delivery idempotency,
calendar/round-robin and the two-step booking controls are retained. Existing
source form data and audit events are not rewritten in bulk. Updated profile
projections and snapshots are computed as eligible turns are processed.

## Verification

`backend/tests/test_sales_delivery2.py` exercises source shapes, empty/manual
profiles, voluntary personal facts, corrections, refusals, withdrawals, exact
proof/scope failures, semantic source classification, explicit objections,
published weights, numeric comparisons, ties, incompatible data, restrictions,
individual units, pending comparisons, displayed order, SMS/WhatsApp and existing
meeting invariants through the production coordinator with scripted inference.

The bundled `docs/sales-ai/delivery-2-verification.json` records final suite
results, base SHA and limitations. These are local regression checks with mocked
models and delivery providers, not proof of a real model's semantic accuracy or
live SMS/WhatsApp/calendar acceptance. PostgreSQL concurrency acceptance requires
a disposable database via `DIALOGUE_POSTGRES_TEST_URL`; SQLite is not a substitute.
The offline production frontend build retains the existing Agent/Sales stylesheet
budget warnings. The later end-to-end acceptance delivery remains necessary.

## Applying the differential ZIP

Overlay the files at the repository root on this base (or after reviewing any
later overlapping changes). The ZIP contains only new/changed source, tests and
this delivery's verification documents; it does not contain dependencies, build
outputs, a repository copy or a root patch artifact. Deploy API and worker at the
same resulting commit using the existing deployment workflow.

```bash
git pull && git add . && git commit -m "Add evidence-backed lead profiles and property comparisons" && git push
```
