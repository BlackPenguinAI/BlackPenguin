# Project onboarding — Block C

Base: `47ff77e8f3e9041984749f4f848f691aedcafc4e` (`origin/main`, Block B).
Date: 2026-11-09.

## Delivered behavior

### One review navigation surface

The duplicate toolbar above the chat is removed. The existing Project review tasks appear once in a responsive panel: a persistent sidebar on desktop and a closable drawer on mobile. The mobile trigger exposes its expanded state and target; the panel supports Escape, Tab/Shift+Tab containment and return of focus to the trigger. Choosing an editor task closes the mobile panel. Property types continues using Block B's local catalog editor without posting a new chat turn.

Task navigation is disabled while an action or website extraction is processing. Requested editor tasks wait for processing to finish rather than interrupting the initial source flow. The conversation retains the mobile viewport when the review drawer is closed.

### Contextual review-later controls

The source-specific defer control is placed inside its identified source-review details after processing. During extraction, the source shows its processing status without a loose Complete later button. Saved deferred-card summaries are hidden during active source processing and become available again afterward.

Project controls use contextual Review [configuration] later / Resume [configuration] text. Meta uses explicit Connect Meta later and Set up campaigns later labels. A question that already offers a defer option does not get another generic defer control.

These label/layout changes retain the existing defer request, draft storage, resumption and server-side approval rules. Company onboarding keeps the shared component's previous default labels unless contextual text is requested. Required reviews and operational readiness retain their existing behavior.

### Meta account first, campaigns by explicit choice

Meta's account review opens first, including when the reusable Company authorization is already connected or its saved state arrives asynchronously. Connection status and accordion disclosure are separate states. Campaign setup opens when the user continues or explicitly requests Campaigns / forms. Switching steps hides projected controls without destroying their values.

Returning from OAuth shows the account review first; a previously persisted campaign task cannot override that initial return state. The existing local OAuth draft restoration and safe navigation remain in place. An explicit campaign task or resumed campaign review can still open step 2 normally.

Saved Meta status is shown within the active Meta review card, never above the initial URL-extraction conversation. User-facing status labels describe connected, permission-review, reconnect, not-configured and verified states without exposing raw enum labels.

For a connected account with incomplete Project routing, Set up campaigns later stays accessible within the Meta card without requiring the campaign form to be expanded. The explanation distinguishes saved Company authorization from pending Project lead delivery. An already verified Project route does not show this setup deferral. A missing/expired connection instead offers the scoped account deferral in step 1.

### Compatibility

The shared review card has an optional controlled disclosure input/output. Existing cards retain their completion/revision-based expansion defaults. Source confirmations, editable property catalogs, PDF/gallery permissions and revocable links from Blocks A/B remain available. No backend production code, database schema, API payload contract or provider configuration is changed by Block C.

## Validation

- Full backend regression: 2123 passed, 4 skipped; 306.90 seconds.
- Full frontend regression: 485 passed (476 Angular tests plus 9 additional DOM tests).
- Production Angular build: passed; only existing stylesheet-budget warnings in agent.scss and sales.scss remain.
- `git diff --check`: passed.

New automated frontend checks cover the single task list; extraction without premature Meta summaries or source deferral; contextual source controls; connected and asynchronously loaded account disclosure; explicit campaign navigation; preserved selections; campaign defer payload without approving facts or revoking Company authorization; account deferral; no duplicate question defer action; verified-route behavior; OAuth return followed by persisted-state loading; mobile Escape/focus restoration and Tab containment; the Block B catalog shortcut; shared-card legacy defaults and preserved projected controls; and shared defer-label compatibility/blocked writes.

The backend suite includes existing independent Meta authorization/routing and campaign deferral/resumption tests, as well as Blocks A/B's creation, approval, property editing, encrypted resources and revocation regressions. Four existing PostgreSQL contention tests require an isolated `DIALOGUE_POSTGRES_TEST_URL` and are skipped without it. SQLite tests do not prove PostgreSQL contention. DOM tests are automated checks, not a browser-based production acceptance or a real Meta OAuth session. Providers are mocked; no production message, connection or deployment is performed.

Reproduction:

```bash
# backend/ — use isolated application test settings.
python -m pytest -q

# frontend/
npm run test:sales-ai-k
npm run build
```

## Apply and deploy

1. Update the repository through Block B or review later changes against the base commit above.
2. Extract the differential ZIP at the repository root, preserving frontend/ and docs/ paths. It contains complete new/modified files, not a full repository.
3. Review the diff and run the checks. No migration, new environment variable or new API endpoint is required.
4. Deploy the rebuilt frontend against the existing Blocks A/B backend.
5. In the deployed environment, verify desktop and mobile: open New Project, start URL processing, review extracted fields, open Property types, open Meta with an already connected account, continue to campaigns, return to account review, defer campaigns, approve the profile and open the Project overview. Check an actual OAuth return with your configured integration as part of deployment acceptance.

Rollback: restore the frontend files in this differential to the base revision and rebuild/redeploy. No database or backend rollback is necessary for Block C. Existing chat, drafts, Company authorizations, Project routing and approved property resources remain stored on the backend.

```bash
git pull && git add . && git commit -m "fix(onboarding): streamline review navigation and contextual Meta setup" && git push
```
