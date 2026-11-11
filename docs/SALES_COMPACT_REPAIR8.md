# Repair 8 · Three observed failures and readable conversation evidence

Based on main `e868be0`. The server's compact battery 2 originally returned 13/16 approved cases, 7/8 bookings, 1,602 PASS and 6 FAIL. Its result is preserved. Recorded cost USD 0.21501390 is partial (139/140 calls); this change makes no paid local model call.

## Runtime changes

- Omit only declared optional property/visit-readiness preferences whose evidence is not current but does appear in the same scoped inbound conversation history. Current, declined and unverified evidence remains subject to normal validation. Stored profile records and consent are not changed.
- This lets the recorded valid slot selection and literal missing-photo request survive their first interpretation, without raising confidence or suppressing restrictions.
- For an explicit flexible new visit, remove only `next seven days` mistakenly duplicated from date evidence into clock fields. Preserve the date range and any actual clock/restriction, exact time relation or ambiguous quotation. No appointment is confirmed by this normalization.
- Prompt version 2.29 reinforces current optional declarations and material requests. Sales model, published configuration, inference deadlines and consent gates stay unchanged.

## Documentation

The main guide includes battery 2's history, costs, diagnosis and next focused evaluation. Its example links open human-readable Markdown first, with original lead/agent dialogue, recorded interpretation and verifiable execution; each page links to its JSON. All 141 recorded conversations have a readable page, including failures. These are deterministic summaries of exported fields, not reconstructed private model reasoning.

The importer retains sanitized interpretation attempts and orders the second full battery after Repair 7. The original PASS/FAIL records remain unchanged. The new page generator checks no external source and calls no model.

## Validation

Recorded native packets replay the three failed journeys through the current core in both SQLAlchemy autoflush modes. Negative cases preserve current preferences, declined or unverified evidence, real clock restrictions and exact-time choices. Seed inventory verification is fixed before the replay clock, so the harness does not incorrectly classify a future-dated quantity as unknown.

Full regression: 3,059 passed, 7 skipped; 130 modules covered exactly once. Acceptance: 63 PASS, 0 FAIL, 1 NOT_RUN (published model quality). Published-model evaluation of Repair 8 remains pending.

## Publish

Extract differential files over the repository:

```bash
git pull
git add .
git commit -m "Fix recorded booking and material failures and add readable sales conversation evidence"
git push
```

## After deployment: server SSH

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases move_up_A downsizing_B portfolio_A \
  --max-calls 80 --max-turns 8 --output /tmp/sales-compact-repair-8
```

Copy even on FAIL:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-8/synthetic-sales-results.zip ~/sales-compact-repair-8.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-8.zip "$env:USERPROFILE\Downloads\sales-compact-repair-8.zip"
```

Target: three cases approved, two visits and one correct no-visit closure. Planned total model consumption USD 0.04–0.09; planning reserve USD 0.08–0.18, not a currency cap. Repeat only failed cases before running the full 16 again.
