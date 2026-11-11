# Financial facts during appointment selection

Base: fc83f6e0d2ec31ac6664d39a1276c73cee708a08 (booking-point-5).

## Observed defect

The initial budget and cash preference survived commit. In all_projects turn 2,
interpretation replayed historical financial values but replaced their evidence
with the current appointment-selection text. Exact-source checking correctly
proved the quote existed, but not that it supported a financial declaration.
lead_profile.capture stores evidence rather than trusting normalized model values,
so both saved financial fields were replaced by the appointment text. The two
budget failures were two observations of the same corruption. Financing was
also corrupted but lacked a separate saved-profile assertion.

## Change

- Prompt 2.18 distinguishes unchanged saved facts from current declarations.
- A bounded semantic guard recognizes appointment selection/confirmation quotes
  that lack financial meaning for the attributed field. Such preferences are
  omitted with an interpretation normalization audit; appointment intent remains.
- Short affirmative answers are omitted as financial preferences only when the
  preceding outbound message carries backend booking_confirmation metadata.
  Generic financial contextual answers are not globally disabled.
- The same guard protects the profile write boundary, including direct callers.
- Genuine explicit financial changes in mixed messages remain eligible for capture.
- The six-case pilot independently checks saved cash and saved budget after each
  commit, through a fresh SQLAlchemy Session with autoflush=False.

This does not implement a general natural-language entailment checker. It fixes
this bounded appointment/financial contamination class without adding model calls,
changing the published model, changing financial values from model output, or
altering booking consent and authorization.

## Validation

Completed offline validation: 59 focused tests passed; full regression 2,615 passed,
7 skipped, 0 failed; all 116 test modules covered once across three shards.
Acceptance registry: 63 PASS, 0 FAIL, 1 NOT_RUN (live evaluation pending).
Focused tests cover the observed
selection, alternative-slot wording, explicit confirmation, mixed financial changes,
short confirmation in booking context, fresh-session persistence and legitimate
correction history. The existing pilot fake-provider tests inject contaminated
budget and financing on both slot selection and Yes; all six routing cases still
run through the real coordinator with both autoflush modes. All inference here is
offline/scripted; deployed-model quality requires the next server evaluation.

## Apply

Copy only the ZIP's differential paths over a checkout at the base or a compatible
later commit. No migration or production data update is required. Existing
corrupted lead profiles are not silently rewritten.

```bash
git pull && git add . && git commit -m "Preserve financial declarations during appointment selection and confirmation" && git push
```

After successful deployment, use a new output directory:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-6
```

An exit status of 2 still produces useful diagnostic evidence. Run the copy as a
separate command even when the evaluation reports FAIL or INCOMPLETE:

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-6/synthetic-sales-results.zip ~/sales-booking-point-6.zip
```

Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-6.zip "$env:USERPROFILE\Downloads\sales-booking-point-6.zip"
```

Expected: three confirmed visits, no meeting in the three unavailable cases,
initial budget and cash declarations retained across every turn, no interpretation
fallback. The three manual future-availability wording checks remain BLOCKED pending
review. Calendar integration, actual channel delivery and PostgreSQL concurrency
are not exercised by this SQLite laboratory.
