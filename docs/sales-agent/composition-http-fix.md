# Commercial composition strict-schema HTTP fix

## Evidence and scope

The supplied sales-lead-diagnostic.json records 14 commercial-composition attempts with HTTPStatusError and safe_fallback. It does not preserve the historical HTTP status or provider response body; therefore no exact historical provider rejection can be asserted from that export alone.

Current main's commercial_composer.py was fetched and matched the local starting file exactly (Git blob 359f9aee04b2198630d3996cea3ce26f3ae12d73). openrouter_client.py was also checked against current main (905ae6d8f6fb546c3605426eb9728d21aba4820c); it is not modified. The composition supplied Composition.model_json_schema() directly with strict=true. The paragraphs field has a local default and is absent from required. This violates the strict structured-output requirement that every property be required. Understanding already normalizes its provider schema; composition did not.

Reference: https://developers.openai.com/api/docs/guides/structured-outputs (all fields must be required). This is a confirmed request-contract defect and a plausible explanation for the historical systematic rejection; the synthetic live probe below confirms or disproves that explanation for the configured provider today.

## Change

- Build a separate strict wire schema: recursively close objects, require all properties, remove defaults. Preserve local Pydantic defaults and semantic evidence/continuation validation.
- Retain bounded fallback and existing retry budgets.
- Record http_status and fixed provider_error_category on HTTP errors. For schema rejection, record only known schema field names mentioned in bounded JSON. Never persist raw error messages/bodies, prompts, tokens, headers or credential values.
- No pipeline, prompt publishing, model selection, database migration, sending, lead capture or business-routing changes.

## Apply and verify

Copy backend/ and docs/ from the differential ZIP to the repository root. Commit and wait until the pipeline has deployed the new commit to API and worker. Do not run the probe before that image contains the new tool.

On the production SSH console:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.probe_composition \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --model openai/gpt-4o-mini --compare-legacy
```

This opt-in probe makes at most two small real OpenRouter requests (256 output tokens each) using synthetic content. Provider usage may incur a small charge. It never sends a lead message, calls messaging providers or writes database/usage records. It obtains the same Company-first/global-configuration fallback credential using direct SQL in a read-only transaction; no ORM registry initialization. It does not print the credential, provider response body or generated content.

Expected confirmation: legacy fails with HTTP 400/422 and structured_output_schema (possibly paragraphs mentioned); corrected returns accepted, HTTP 200. If corrected still fails, share the short sanitized JSON. A failure with authentication, credit, rate-limit or upstream status requires resolving that provider condition instead of relaxing evidence validation. The old provider error is intentionally reproduced only when --compare-legacy is supplied. Without it the command makes one corrected-schema call.

The probe establishes provider/schema acceptance with synthetic data; it does not establish complete live conversational quality. A subsequent real or isolated-engine turn should record composition.status=accepted rather than safe_fallback. Earlier logs are not changed or reprocessed.

## Validation

- 142 tests passed across test_sales_composer_http.py (first 10 cases), test_sales_delivery3.py and test_sales_ai_group_b.py; 37.37 seconds.
- Focused suite rerun after adding probe coverage: 11 passed in 0.67 seconds (143 distinct tests across both runs).
- Real HTTP client path exercised with MockTransport: original schema rejected by a strict-contract emulator, corrected composition accepted and rendered; no real provider calls.
- Unknown evidence remains rejected; HTTP fallback remains safe; status categorization and redaction tested; local schema defaults unchanged.
- git diff --check passed.

No live OpenRouter request or production deployment was executed during preparation. Full current-repository CI must pass. This fix does not address the separate budgeting, cash, parking or material-selection issues identified in the conversation.
