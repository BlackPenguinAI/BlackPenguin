# Delivery 3 — Reviewed resources and natural Sales replies

Base: `ac33b0041c500b020379e2110e09e1dfee40f42d` (Delivery 2).
Scope: SA-05 and SA-06. Later human takeover, inactivity and final acceptance
work remains separate; this is not acceptance of every business scenario.

## SA-05: material coverage and delivery

A material can now have explicit reviewed coverage for multiple property types
or individual units in the same Project. Each entry lists its content types,
optional PDF page references and a short description. Disjoint content types can
have separate page references for the same target. Duplicate content entries,
foreign targets, unsupported content types and invalid page numbers are rejected.
Page counts are checked against actual PDF bytes at approval.

Coverage is user-reviewed metadata, not an inference from a filename, MIME type,
website text or presumed photo contents. A PDF can contain approved photos; an
image can contain an approved floor plan. Property-level coverage is not proof
of coverage for an individual unit. Missing confirmation is not unavailability
or zero inventory.

The source/material cards and the saved property's PDF card include **Edit
coverage**. The editor loads only the current Project's targets and supports
adding/removing associations, changing content types and page references. Saving
returns the material to draft, increments its version, revokes previous audited
links and requires a fresh explicit approval. Existing upload, private-file,
gallery and preview flows remain available. Regenerating a property's gallery
reaffirms that property's selected images, not stale coverage or content roles
for another property.
Shared galleries appear as separate materials on the covered property's card;
its image-selection controls continue to manage only its own generated gallery.

**Page references are navigation hints, not redaction. Shared links open the
whole file.** The editor explains this before saving. Administrators must review
all covered targets and contents. An indivisible file is withheld if it would
include an explicitly prohibited covered target or material type. Separate
redacted documents require separate uploaded files.

Generic requests for photos, floor plans or a unit sheet first ask which option
when several property types are available. Choosing the option resumes the
original request without requiring it to be typed again. Existing interest is
used when already known. This does not imply visit consent or modify a booking.

A file satisfying several independent requests is issued once per exact binding
while retaining each fulfilled task. The model does not create URLs or send
attachments. The backend issues audited links for SMS and WhatsApp, checks file
bytes/hash, scope, channels, approval, validity, source and target version, and
revalidates before dispatch and access. Reviewed external resources use the same
opaque audited-link route; they are not fetched during a turn or reproduced
from runtime context in factual prose.

After sending requested photos, the agent can offer separately approved floor
plans for that option (and vice versa). An exact current proposal, with immutable
file/resource snapshots, must be accepted before those additional links are
issued. An expired, changed, revoked or partially delivered offer cannot silently
substitute another file. Material proposal expiry also respects the shared
conversation clock used in simulation.

When requested material is missing, the reply identifies the missing resource,
offers useful approved alternatives for the same target when available, and
continues without a human pause. A partial answer discloses the missing part;
an already-sent alternative is not sent again merely because another resource
was unavailable. Accepting related material does not turn its unconfirmed
coverage into confirmed coverage.

Encrypted files retain the 50 MB plaintext read limit. The on-disk check allows
Fernet framing/base64 overhead, so an otherwise permitted gallery is not rejected
solely because its encrypted bytes are larger than its plaintext.

## SA-06: grounded conversational synthesis

The interpreter advances to `sales-understanding-prompt/2.10`. Existing model,
business playbooks, published configuration and mandatory-current-workflow rules
remain in force. No engine toggle, Company cohort or Project opt-in is added.

The backend now synthesizes repeated catalog, availability and pricing reads into
one ordered presentation instead of stacking repeated diagnostic catalogs.
Property/unit references follow the actual displayed order. A focused property
question can name bedrooms, bathrooms, area, kitchen, features or description;
the reply answers those fields rather than dumping every property attribute.
Unknown individual-unit details are stated as unconfirmed rather than inherited
from a different option or invented.

The model can select supplied natural formulations, group grounded statements
into paragraphs, and choose a useful continuation or **none**. Mandatory
clarification, material proposals and booking confirmations remain visible.
Facts and uncertainties stay bound to backend evidence; paragraph grouping cannot
add a free assertion, omit required evidence, reorder offered properties or
invent prices, benefits or completed actions. This deliberately supports flexible
structured synthesis rather than unrestricted model-authored commercial claims.
Optional marketing statements with promises of guaranteed returns/performance,
or unapproved source URLs, are not promoted into factual Sales replies.

A current personal setback, feeling unwell or frustration can receive brief
empathy and a gentle return to the last property topic, without a forced sales
question. It is not automatically hostility, a medical diagnosis, an objection
or a commercial profile fact. Existing security/threat checks and genuine
harassment controls retain precedence. The agent continues to identify as AI;
none of the new wording claims to be a human representative.

## Database and compatibility

Migration: `20261109_sales_asset_coverage`, following
`20261108_sales_moderation`. It adds nullable JSON `project_sales_assets.coverage`.
No dependency, service account or environment flag is added. Existing approvals
are not rewritten or inferred during upgrade. SQL NULL retains the legacy
single-property/Project-wide semantics and the previous snapshot/signature shape.

New explicit-coverage approvals use internal status `approved_targeted`; the API
still returns `approved` to existing clients. Older approved-only runtimes do not
silently ignore the new targeting and share those materials. Older clients that
omit the coverage field preserve existing targeting when saving metadata. An
explicit new review cannot be reset to ambiguous legacy targeting by sending
null; choose named targets or an explicit Project-wide entry.

Downgrade revokes links and removes approvals for resources using the new column
before dropping it, rather than turning targeted resources into approved global
legacy files. Existing conversation audit data is preserved. An older strict
reader is not guaranteed to understand new interpretation/state fields: deploy
API and worker at the same revision. The existing deployment workflow detects
the migration/model change and runs `alembic upgrade head`; do not omit the
migration from the differential ZIP.

## Verification and application

The differential includes tests for API authorization and scope, coverage/page
validation, legacy compatibility, file integrity, encrypted size limits, targeted
approval status, migration/downgrade, pending-request resumption, partial material
answers, exact complementary/alternative proposals, expiry/revocation,
SMS/WhatsApp delivery receipts, current bookings, empathy, focused details,
paragraph evidence and the Angular coverage editor.

See `delivery-3-verification.json` for the final regression results. The complete backend suite is executed in three recorded batches. Their file
inventory is checked against the complete collected suite, including the root
lifecycle tests. Final resource/onboarding checks supplement that run, and
frontend tests/build cover the final client sources.
Sales inference and provider calls are scripted/mocked: these are local regression
checks, not live model, phone or calendar acceptance. PostgreSQL concurrency
checks require a disposable `DIALOGUE_POSTGRES_TEST_URL`; SQLite is not a substitute.
The frontend retains the existing Agent/Sales stylesheet budget warnings.

Overlay the ZIP's new/changed files at the repository root on this base, reviewing
any later overlapping changes. It contains source, tests, the incremental migration
and verification documents, with no dependencies, build outputs or root patch file.

```bash
git pull && git add . && git commit -m "Add reviewed multi-property resources and natural sales replies" && git push
```
