# Repair 7 · Current visit after history and deterministic booking receipt

Based on main `1e561fb`, after the server Repair 6 archive (`a5c7b6d`). No migration, model change, new paid local inference or production database operation.

## Observed problem

Repair 6: 2/3 cases approved, 2/2 bookings. `move_up_B` now passes. In `first_time_A` turn 3, the first interpretation replayed two historical questions (`evidence_mismatch`); its repair timed out. The lead had to repeat the visit request. At confirmation the composer timed out after about 8 seconds, although the booking was saved correctly.

## Changes

- Pass only scoped previous inbound user messages to the input compiler. For an affirmative current visit directive, omit standalone informative requests whose evidence is absent from the current message and present in that history. Current independent questions, exclusions, OR groups, restrictions, unknown quotations, human/opt-out/appointment requests and confidence remain subject to normal validation. Saved preferences remain intact. No booking consent is inferred.
- Explain current-vs-historical requests in prompt 2.28.
- Render a single complete backend-prepared booking receipt directly when a meeting and booking operation exist and the sole continuation is none. Extra questions/evidence retain normal model composition. Trace `backend_rendered`, `model_called=false` and zero attempts; do not disguise a provider fallback as a model acceptance.
- Evaluation recognizes this specific successful backend path; provider/contract errors retain their failures. Existing booking, consent, scope and idempotency checks stay in force.
- README adds a table of server-observed successful flows and conditions for real leads, plus data consistency guidance. It distinguishes historical successes, current reliability limits, local replay and future published-model evaluation.

## Validation

Recorded Repair 6 native packets replayed through the core for all three cases, both session autoflush modes; first-time visit progresses without repeated inbound. Negative and mixed cases ensure recovery stays narrow. Full regression: 3,041 passed, 7 skipped; 129 modules covered exactly once. Final focused module: 22 passed (18 in full regression, 4 additional negative cases checked afterward). Acceptance: 63 PASS, 0 FAIL, 1 NOT_RUN (live model quality). No paid provider call was made locally. No new live quality result is claimed.

## After deployment: SSH

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B unknown_A \
  --max-calls 60 --max-turns 8 --output /tmp/sales-compact-repair-7
```

Copy even if the evaluation reports FAIL:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-7/synthetic-sales-results.zip ~/sales-compact-repair-7.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-7.zip "$env:USERPROFILE\Downloads\sales-compact-repair-7.zip"
```

Expected target, not measured outcome: 3/3 cases, 2/2 visits, no repeated request, correct gallery and explicit consent. Same model/configuration. Planned total recorded-model spend approximately USD 0.04–0.09, reserve USD 0.08–0.17; not a guaranteed cap. No automatic retry of the entire evaluation on failure.

## Local publication

Extract the differential files into the repository, then:

```bash
git pull
git add .
git commit -m "Prevent historical request replay and render verified booking receipts without model inference"
git push
```
