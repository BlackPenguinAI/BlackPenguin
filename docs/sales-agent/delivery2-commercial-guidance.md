# Delivery 2 — commercial information and visits

Base: 4b807110d3a8d60d3a2b2b88bc7a7873b6eb3f68.

## Behavior

The backend supplies mandatory evidence blocks and the permitted next question to
the existing composer. Published model and staff configuration remain unchanged.
Understanding prompt is version 2.19. There are no additional inference stages,
production writes from evaluations, payments or purchase reservations.

- Cash is an outright purchase preference, never physical banknotes, a verified
  balance or a payment action. It does not produce an invented financing question.
- Down payment/deposit amounts are not captured as total purchase budget. A guard
  also prevents historical/form down-payment text from being used as a budget cap.
  The agent asks for the total purchase budget/currency when needed.
- Total-budget comparisons require an explicit comparable cap and currency. No
  exchange rate is assumed. Ambiguous totals/currencies receive clarification.
- Alternatives come only from this turn's approved, tenant/project-scoped catalog.
  Known sold-out types, sold units, missing prices and different-currency options
  are excluded. Unknown stock is not described as guaranteed available. Starting
  prices remain starting prices; the exact property and availability need checking.
- Individual-unit catalogs use the listed price and status of actual units.
- If no price fits, the agent may discuss financing explicitly present in approved
  payment_methods. It cannot guarantee approval, invent a discount or claim that
  financing changes the property price. A stated outright preference is respected.
- Published financing information is answered before the invitation. Detailed
  financing/down-payment conditions can be reviewed in person; no eligibility or
  approval is established in chat. Missing published terms are reported as unknown.
- If no appropriate alternative/payment discussion applies, the agent asks whether
  there is another question and offers a polite conditional goodbye.
- Requests to pay or reserve a property receive an informational boundary. An
  explicit property transaction alone cannot authorize visit scheduling. A separate
  explicit visit request still follows the normal selection and confirmation flow.
- Existing reference clarifications, material offers, booking proposals, bookings,
  action holds and persistent visit refusals take precedence over generic next steps.

The policy has no access to other companies/projects and does not send alerts,
create human handoffs, change Calendar integration or implement silence follow-ups.
Those remain later work. It does not rewrite previously corrupted lead profiles.

## Validation

Focused tests exercise the policy and the real shared coordinator with fake model
HTTP responses, fresh post-commit profile reads and both autoflush settings. Full
regression: 2,666 passed, 7 skipped, 0 failed; 118 modules covered exactly once.
Acceptance: 63 PASS, 0 FAIL, 1 NOT_RUN (live acceptance pending). These are
not quality measurements of the live published model.

The new `commercial-point` suite contains eight short scripts (17 lead messages):

| Case | Project | Goal |
| --- | --- | --- |
| cash_available | Harbor Gardens | Cash available is an outright funding preference |
| outright_purchase | Harbor Gardens | Variant of cash purchase declaration |
| affordable_alternative | Cedar Heights | USD 250,000 cap suggests Studio starting USD 210,000 |
| lower_budget_financing | Harbor Gardens | USD 500,000 cap; only published Bank financing discussed |
| no_budget_match | Sierra Commons | USD 100,000, cash-only project; no false match/promise |
| down_payment_only | Cedar Heights | USD 50,000 initial is not total; then USD 250,000 total |
| different_currency | Harbor Gardens | EUR cap is not silently compared with USD prices |
| property_reservation | Harbor Gardens | No payment/hold and no unrequested visit |

All use the existing private synthetic company, three projects and six types with
galleries/PDFs. Only this suite's private Sierra approval is cash-only; catalog.json
records published payment_methods. Leads are scripted; no lead model or judge.
The real coordinator, published Sales model, interpretation, tools, composition,
profile persistence and safeguards run unchanged. No production lead data is read.
No script requests a visit, so no Meeting should be created; retain the separate
booking-point suite to verify the three positive bookings and three unavailable cases.

## Deploy

Extract the differential ZIP over a checkout at the base (or a compatible later
commit); no migration or staff model change is required.

```bash
git pull && git add . && git commit -m "Add budget-aware sales guidance and scripted commercial evaluation" && git push
```

After successful deployment, run the new focused suite in a new output directory:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite commercial-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 96 --max-turns 3 \
  --output /tmp/sales-commercial-point-1
```

96 is a call cap, not a dollar cap. Actual token usage and provider-reported cost
are exported in the report. Exit status 2 still exports failures for diagnosis.
Run copy separately even if the evaluation reports FAIL/INCOMPLETE:

```bash
docker cp bp_api_prod:/tmp/sales-commercial-point-1/synthetic-sales-results.zip ~/sales-commercial-point-1.zip
```

In Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-commercial-point-1.zip "$env:USERPROFILE\Downloads\sales-commercial-point-1.zip"
```

For an additional live booking regression, run booking-point with max-calls 120,
max-turns 8 and a new output `/tmp/sales-booking-point-7`; copy and download the
result as sales-booking-point-7.zip. This uses additional paid inference and is
separate from the offline CI booking checks. The three availability wording
reviews remain pending; the commercial suite does not validate future alerts.
