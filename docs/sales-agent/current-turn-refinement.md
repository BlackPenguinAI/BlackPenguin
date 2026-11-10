# Current-turn interpretation and customer-facing recovery

Base: 80d339c9f74ee2a8d74184c9d7337e7b6e789ec2.

## Changes

- Version 2.13 interpretation guidance distinguishes declarations from project-policy
  questions, preserves independent questions, explains local material references,
  and includes budget, cash, correction, negation and feature examples.
- The provider schema bounds evidence length by the actual current message. Exact
  substring validation remains authoritative; punctuation is not silently removed,
  and history cannot supply current evidence or consent.
- One bounded repair receives the exact short source quote, local-reference rule,
  field diagnostics and current-turn instructions. No extra retries or model calls
  are added. Rejected resumed interpretations cannot replace accepted state.
- The audited prompt snapshot includes the complete reinforced system instruction.
- Internal failure notifications and traces remain available to staff. Customer
  recovery offers assistance without exposing technical processing or claiming a
  transfer has happened. Repeated failures no longer silently suppress replies.
- The composer no longer prefixes replies with verification narration.
- Common English budget/payment terms reach interpretation through the language gate.
- Each evaluation turn checks for known internal-processing narration. This lexical
  regression check does not prove overall conversational naturalness.

## Automated variants

The existing replay (four conversations, fourteen messages) remains unchanged.
`--mode variants` runs nine separate conversations with twenty-two messages:

| Conversation | Coverage |
| --- | --- |
| budget_variant | Budget, currency, explicit cash |
| cash_correction | Correction, cash retention, financing plus property question |
| feature_variants | Parking, garage, bedrooms and bathrooms |
| material_acceptance | Photos, contextual acceptance, explicit PDF |
| cash_negation | Negative cash declaration followed by explicit correction |
| courtesy_with_question | Courtesy plus area and amenities questions |
| cash_boundaries | Third-party cash and hypothetical payment |
| informal_details | Informal wording, garage and area |
| budget_private | Declined optional qualification |

The material-acceptance delivery assertion applies only if there actually was a
current material offer; direct PDF delivery still requires a resource. Missing
approved source bytes remain BLOCKED rather than fabricated successful delivery.
The same isolation, call budget and no-provider-send guard apply to all modes.
Scripted offline model responses validate contracts and engine behavior; they do
not establish that the live model interprets these cases correctly.

## After deployment

Run these sequentially over SSH. Each is isolated and read-only against the source
production data; model inference consumes the configured OpenRouter credit.
The call cap is not a currency spending cap. Exit code 2 means review the report,
not necessarily a command failure. Do not join commands with `&&`.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.evaluation \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --project-id 854ac168-1b0b-5ef3-a68e-091b5cc82e0f \
  --mode replay --max-calls 80 --no-judge \
  --output /tmp/sales-refinement-replay

docker cp bp_api_prod:/tmp/sales-refinement-replay/report.json ./sales-refinement-replay.json

docker exec -i -w /app bp_api_prod python -m tools.sales_ai.evaluation \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --project-id 854ac168-1b0b-5ef3-a68e-091b5cc82e0f \
  --mode variants --max-calls 120 --no-judge \
  --output /tmp/sales-refinement-variants

docker cp bp_api_prod:/tmp/sales-refinement-variants/report.json ./sales-refinement-variants.json
```

Download with Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-refinement-replay.json "$env:USERPROFILE\Downloads\sales-refinement-replay.json"
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-refinement-variants.json "$env:USERPROFILE\Downloads\sales-refinement-variants.json"
```

Compare exact interpretation failures, evidence and reference errors, captured
facts, current-question answers and delivered receipts. An accepted composition
alone is not a successful sales conversation. The LLM semantic judge is excluded
here because the prior report exposed false positives; manual report assessment
and deterministic assertions remain complementary.

## Local validation

377 tests passed across current-flow integration, interpretation recovery, profile
memory, composition, evaluation isolation, materials and human-control recovery.
No live inference was used for these tests.

## Limits

No live provider/model requests were made while preparing this patch. Existing
catalog verbosity, complementary-resource ranking and semantic judge calibration
are not resolved by this change. This is an instrumented improvement requiring
live replay comparison, not a claim that conversational quality is already proven.
