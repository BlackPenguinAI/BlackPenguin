# HEI-07B.2 — Semantic Autonomy & Commercial Continuity

**Candidate / Upload Ready** — base `f8932f6` (`f8932f6b8369f0de58bbf2d9528f8e91bab3c3e9`).

## Scope and evidence

The manually tested Cedar conversation consolidated four turns, persisted Cleveland as focus, recorded three bedrooms and delivered its approved gallery. The next inbound (`Do you have blueprints?`) reached the SDK, which returned HTTP 409. Its container was running, without restart or OOM kill. The API had no persisted draft or provider outbox for that turn. The old SDK conflated a busy lock with internal preparation errors. The historical exception cannot be recovered from that log; this candidate does not claim to have reproduced it.

## Changes

- Private SDK returns a bounded diagnostic header on internal review and records sanitized checkpoint, exception class and source location. The API retains the HTTP status, classification and remote diagnostic in the inbound failure metadata. No raw exception text, credentials, customer content or access links are added to logs. Existing HTTP status and detail contracts remain.
- Only the exact HTTP 409 busy response (lock not acquired) enters the normal worker's bounded retry lane, up to five total claim attempts. It reuses the original pinned job/run, revalidates scope and does not send or replay an external effect. Other conflicts, transport uncertainty and authorization failures remain reviewable; no automatic LangGraph fallback.
- `get_unit_media` can return approved metadata alternatives on an ambiguous or unavailable material request instead of requiring the old lexical classifier to understand every phrase. `list_unit_assets` also records successful read-only discovery for safe recovery. The model still decides meaning; the approved property/channel catalog determines facts. The original authorization for actual shares is unchanged. A floor plan and a brochure are different types, regardless of filename.
- For a narrowly read-only material discovery with no new preference, booking, search or share effect, a missing SDK text response or a rejected monetary/language reply can be replaced by a truthful catalog-based clarification. That response must pass the existing output guards. Other failures remain reviewable. No second model call is added.
- A search matching the already verified contextual bedroom declaration exactly is marked permanent instead of temporary. Other filters or exploratory requests retain their existing semantics.
- The panel's current enquiry uses the scoped, current Hermes Inspector focus when available and preserves the historical/legacy view otherwise. The Refresh action does not break into individual characters in narrow sidebars. No CRM state is fabricated to satisfy UI presentation.
- The provisional material message is more natural. The existing authorization, outbox and receipt sequence is preserved.

## Deliberate limitations

This is an incremental candidate, not full commercial certification. It does not remove the provisional message entirely: a single customer-facing message with an authorized link would require reworking the transaction that currently binds material effects to a prior accepted reply. It does not enable unrestricted `update_lead_profile`, direct sharing based solely on semantic model arguments, or bare assent to a material offer; for a delivery, use the explicitly named approved category (e.g., `Please send the brochure`). The read-only semantics of synonyms are supported; direct delivery authorization still follows the existing evidence contract. The exact original internal 409 may arise from another guard; the new diagnostic will expose its location and class. No old failed job is automatically replayed, and no historical state is rewritten. Existing production controls for LangGraph, onboarding, Calendar, consent, storage encryption, and tenant isolation are unchanged.

## Files

Updated (original Git blob SHA verified against the base):

- `backend/app/modules/hermes_sales_core/live_job.py` — `e56d42d2c0759a0451b8a9d39c1cdca9076d39d3`
- `backend/app/modules/hermes_sales_core/live_preparation.py` — `e6bc586b0d6830c88cc7834433f894369c8e4900`
- `backend/app/modules/hermes_sales_core/sdk_service.py` — `0f032a48d6639202b31859f69259cc96d5b5032d`
- `frontend/src/app/shared/ui/agent-context/agent-context.html` — `3653b454e8b33f03589215e2b3587c266aeb91b4`
- `frontend/src/app/shared/ui/agent-context/agent-context.scss` — `0ea5bf3274bf6aa594fb319d09c0fb494b3f0fba`

New:

- `backend/app/modules/hermes_sales_core/sdk_diagnostics.py`
- `backend/app/modules/hermes_sales_core/semantic_material.py`
- `backend/tests/test_bp_hei07b2_semantic_continuity.py`
- `backend/tests/test_bp_hei07b2_live_integration.py`
- `docs/hermes-integration/HEI_07B2_SEMANTIC_AUTONOMY_AND_COMMERCIAL_CONTINUITY.md`

## Validation

Locally: 30 pure offline pytest cases passed; Python syntax compilation passed. The offline tests cover the diagnostic response contract, lack of raw exception propagation, semantic discovery, unavailable categories, existing explicit delivery evidence, safe read-only recovery and contextual search classification. The new ORM tests use the existing real-lane fixture and exercise retry/attempt exhaustion and the Cedar-like approved brochure query. They were added but not executed locally because the full backend repository and Docker environment were not available. Angular build and complete regression must run in the normal GitHub Actions workflow. The exact live SDK, Telnyx, and Calendar behavior has not been tested on this candidate.

## Deployment and acceptance

1. For the existing deployment preflight, temporarily select LangGraph in Sales Agent and stop test traffic. Verify no Hermes work is in flight. Do not modify the published Hermes policy.
2. Extract the Upload Ready archive and upload all files at their existing paths to the repository root. Suggested commit: `fix(hermes): recover semantic material discovery and diagnose private SDK conflicts`.
3. Verify the automatic deployment and HEI-06 isolated evaluation. Confirm `hermes_private_transport=ready` and the new release SHA. No new secrets, migration, Droplet, or staging workflow required.
4. Select Hermes explicitly after deploy. Keep the same prompt/model/12 iterations. Use a fresh test lead/conversation on Cedar; do not replay the historic review job.
5. Reproduce: 2 bedrooms → accept 3 bedrooms → pick Cleveland → photos → `Do you have blueprints?`. Verify gallery link, a response to the last turn, stable Cleveland focus, and state/CRM preferences. If only a brochure is approved, an answer acknowledging that distinction is correct. Send `Please send me the brochure` and open the returned link. Then ask about area and switch to Van Buren. Verify the Inspector's current enquiry and all work statuses.
6. Try `Can I see its architectural drawings?` as a separate discovery query. Do not expect a file to be delivered unless the type is approved and the explicit delivery contract is met. Confirm no unexpected asset, URL, duplicate send or booking.

If a new turn fails, gather only the new diagnostic from the recent window (read-only):

```bash
docker logs --since 20m bp-hermes 2>&1 | grep -E 'Hermes SDK preparation failed|Hermes read-only recovery|POST /internal/prepare' | tail -40
docker logs --since 20m bp_worker_prod 2>&1 | grep -E 'Hermes SDK preparation outcome|Hermes inbound requires review' | tail -40
```

The key fields are `sdk_http_status`, `sdk_error_code`, and `sdk_failure` (checkpoint, exception_type, locations, optional sqlstate). If the failure is still HTTP 409, the new log can now distinguish `SDK_BUSY` from `SDK_PREPARATION_REVIEW`. Do not manually resend a historical provider message or mutate the job/state tables to force completion.
