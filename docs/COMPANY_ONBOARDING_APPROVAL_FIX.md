# Company onboarding · approval routing fix

## Problem and cause

On main `3363d1f`, clicking **Approve profile** sent the label with the final card ID. Company `/chat` classified that label as navigation (`review`) before resolving card actions. It superseded the current question, created another review and returned `profile_changed=false`; the approval service was never reached. The screenshots' repeated “I understood: Review the Company Profile…” match this branch. Project onboarding already gave bound card responses priority.

## Resulting behavior

- An answer explicitly bound to a card is resolved against that exact card before navigation. A stale or foreign card cannot silently approve a newer review.
- Legacy text without a reply ID resolves against the active approval card, including older boolean final-review cards.
- **Review / approve profile** in the sidebar explicitly sends a navigation request without binding the current question. It opens review and does not approve.
- **Approve profile** publishes only after existing authorization, completeness and location-consistency checks pass. Marketing is still forbidden. A document card is not a final approval card.
- Successful approval stores the published snapshot, completes the session and returns completion to the client. The existing UI then opens `/app/company`.
- Duplicate submissions do not republish the same revision. Historical messages remain visible; no profile data or team configuration is erased.

No migration, model inference or re-entry of the Company profile is required. The fix does not change Project onboarding or Sales Agent behavior.

## Verification

HTTP tests use the real router, services and an isolated SQLite database: bound/unbound typed and legacy approval, review navigation, missing required fields, stale and foreign card IDs, duplicate submission, Marketing denial, inconsistent location and a document card. Model/crawl calls are prohibited in these tests.

Frontend tests submit the final card, verify navigation only after completion, and keep sidebar navigation unbound. Onboarding regression: **267 UI tests passed**; TypeScript regression configuration passed. Full backend regression: **3,071 passed, seven skipped**, with 131 modules covered once. All checks completed without model/provider calls. Production frontend build also passed.

## Publish and check

Extract the differential files over the updated repository, then:

```bash
git pull
git add .
git commit -m "Fix Company onboarding approval routing and preserve explicit review navigation"
git push
```

After deployment, reload the app to load the updated frontend. Return to the existing Company onboarding and use its latest active **Approve profile** card. With a complete, valid profile it should open the Company summary. It is unnecessary to recreate the company or repeat the onboarding. Older superseded cards remain historical and do not approve.

If there are real pending required fields or inconsistent country/timezone data, approval remains blocked; resolve those inputs first. A 100% completeness indicator alone is not final approval.
