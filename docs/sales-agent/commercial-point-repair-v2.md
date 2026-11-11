# Commercial-point repair after the first live-model evaluation

Base: bf5bd88dbefd6a5532593c5e4873699bf6a5a443.

The first commercial run had 129 PASS / 1 FAIL, but manual review found six
neutral farewells mislabeled as frustration, two declarations turned into
questions, and duplicated payment information. The checks did not cover all
these errors; a PASS count was not a complete dialogue-quality assessment.

## Repair

- Prompt 2.20 clarifies cash plus no need for financing, neutral goodbyes and total
  purchase budget declarations. The published Sales model/configuration is unchanged.
- Bounded financial-declaration helpers distinguish negating the need for a loan
  from negating cash itself. A property question in another sentence does not erase
  a preceding own cash declaration. Missing cash still requires the existing single
  repair; no unverified financing preference is inserted by the backend.
- Exact cash and total-budget declarations are not questions about project financing.
  Pure invented requests can be omitted with an audit record, retaining preferences
  and real independent requests. Ambiguous linked requests still require repair.
- Neutral courtesy evidence is not sufficient for frustration/illness. The optional
  affect is omitted with a normalization receipt. A second renderer guard prevents
  the same unsupported wording through direct callers. Genuine emotional evidence
  and genuine financing questions are retained.
- Published payment information and the detailed-conditions disclaimer are independent
  shared blocks, each emitted once. A low-budget financing offer no longer repeats
  their content inside another block. A deposit clarification does not repeat terms.

These are bounded rules, not a general semantic entailment model. No payments,
property holds, extra inference stages, alerts or migrations are introduced.

## Stronger evaluation

The same eight scripts/17 lead messages now check neutral closures, declarations
converted into questions, unrequested financing pitches after cash, duplicate
sentences/payment facts, and saved cash preferences separately from reply wording.

Rechecking the original report with the new checks exposes:
- 6 neutral closures with invented emotion;
- 2 declarations converted into questions;
- 1 unrequested financing pitch after cash;
- 1 response with repeated financial sentences/payment information.
Some checks describe the same defect, so these counts are not independent failures.

Offline HTTP tests inject the observed mistakes: cash missing on attempt one,
false frustration on each farewell and a financing request invented from a total
budget statement. Negative, hypothetical, reported and genuine-question variants
are also tested. Local fake-provider success does not prove live model quality.
Final offline regression: 2,687 passed, 7 skipped, 0 failed; 119 modules
covered exactly once. Acceptance: 63 PASS, 0 FAIL, 1 NOT_RUN (live acceptance pending).

## Apply and evaluate

Extract the differential ZIP over the base or a compatible newer checkout:

```bash
git pull && git add . && git commit -m "Fix cash interpretation, neutral farewells and repeated financing replies" && git push
```

After successful deployment, run on the server with a fresh directory:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite commercial-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 96 --max-turns 3 \
  --output /tmp/sales-commercial-point-2
```

The call cap is not a dollar cap. Reported usage/cost is exported. Copy even if
this command returns exit status 2 (FAIL/INCOMPLETE), as a separate command:

```bash
docker cp bp_api_prod:/tmp/sales-commercial-point-2/synthetic-sales-results.zip ~/sales-commercial-point-2.zip
```

Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-commercial-point-2.zip "$env:USERPROFILE\Downloads\sales-commercial-point-2.zip"
```

The worker remains isolated: private synthetic data, no production database writes,
no real lead contacts, and only the existing Sales provider calls. Actual transport,
Google Calendar and notification automation are outside this suite. Eight scripts
are not coverage of every segment or dialogue variation.
