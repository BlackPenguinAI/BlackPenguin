# Project onboarding — Delivery 3: location search and Meta continuation

Baseline: `22704ac950b780879f3620e9640b4a00f5a1bf2c` (editing/current-approval delivery 2).
Apply this delivery's differential files at the repository root.

## Location and timezone

- Project/Company location editing reuses the searchable timezone selector used by profiles, with city/IANA/UTC-offset search and the same option presentation.
- Onboarding limits options to the server-provided country/city timezone list. Unknown cities still require an explicit timezone choice. Selecting/searching never submits the location; Confirm location remains explicit. The backend's country/city/IANA checks are unchanged.
- The shared dropdown is appended to body and uses isolated global panel styles, so profile/onboarding cards cannot clip it. It can choose an opening direction automatically. The component closes it on outside-container scrolling/resizing rather than leaving a detached list at the old position, while scrolling the options remains usable.
- Dropdowns and listeners are cleaned up when the editor closes or is destroyed. The combobox has a unique linked accessible label. Disabled controls cannot emit a new selection.
- Confirming a location cannot move existing appointment instants; Project timezone changes still require profile approval.

## Meta connection

- One heading/status per step; the redundant Saved Meta setup summary and repeated inner titles/status paragraphs are removed.
- A Meta connection mark identifies the section. The collapsed account header includes the account name returned by the server, without showing internal Meta user IDs or credentials.
- The OAuth return first shows Checking your saved Meta connection. Only authoritative connected setup state permits automatic continuation: Step 1 collapses and Step 2 opens, with available asset discovery as a read operation. Permissions-required/reconnect/error states do not claim success.
- A saved connected account also opens Step 2 on initial loading unless the user explicitly requested/reopened account review. Subsequent status refreshes do not override a manual disclosure choice; the explicit finished-authorization refresh can continue to Step 2 after verification.
- There is no Continue to project campaigns button in Step 1. Campaign review offers Refresh available Meta assets and keeps Set up campaigns later inside Step 2.
- OAuth connection, asset discovery and campaign association remain different operations. No campaign/Page/Form is associated or activated until the user explicitly saves/verifies it. Deferring campaign setup preserves Company authorization.
- OAuth drafts now also preserve unsaved campaign form selections. Cancellation/start failure/status-read failure retain the draft; retries are available. Invalid/removed account selections are reconciled against authoritative options.
- Older authorization/setup responses cannot clear a later confirmed account or overwrite its current status.

## Compatibility

No backend code, schema migration, new production environment variable or dependency. Existing Company-level OAuth storage, Project-specific routing verification, manual fallback, profile approval and resource-sharing permissions remain in force. The dropdown presentation also improves existing profile selectors through the shared component.

## Validation

- Frontend: **303 tests / 30 files passed**, including rendered searchable body-overlay selection, exact IANA emission, country-scoped options, disabled/free-text rejection, scrolling/cleanup, OAuth identity/continuation, incomplete permissions, cancellation, retry and stale-response handling, plus deliveries 1/2 regressions.
- Backend compatibility: **163 passed** across location editing, team/Meta setup, asset discovery, prior onboarding, current approval and public resources. Provider calls use test fixtures/mocks.
- Production/offline-CI Angular build passed; existing agent.scss and sales.scss stylesheet-budget warnings remain. The Meta asset is included in the compiled output.
- No live Meta OAuth, production mutation or real-browser visual walkthrough was performed here. Rendered DOM tests validate body placement and cleanup; pixel positioning, mobile interaction and live identity/permissions should be checked after deployment.

Frontend command:

```bash
cd frontend
npx ng test --watch=false --ts-config=tsconfig.onboarding-regression.json --include='src/app/pages/client/projects/project-chat/*-*.spec.ts' --include='src/app/pages/onboarding-*.spec.ts' --include='src/app/shared/ui/onboarding-*/*.spec.ts' --include='src/app/shared/ui/configure-later/*.spec.ts' --include='src/app/shared/ui/public-resource-link/*.spec.ts' --include='src/app/shared/ui/timezone-select/*.spec.ts' --include='src/app/pages/client/projects/project-overview/*.spec.ts' --include='src/app/pages/client/marketing/*.spec.ts' --include='src/app/core/timezones.spec.ts'
npx ng build --configuration production,offline-ci
```

Backend compatibility command (with the usual test environment):

```bash
cd backend
python -m pytest tests/test_editor_1316.py tests/test_team_meta_101112.py tests/test_meta_asset_discovery.py tests/test_project_onboarding_block_a.py tests/test_project_onboarding_block_b.py tests/test_project_current_approval.py tests/test_public_property_resources.py -q
```

## Production smoke check

1. In Project onboarding, enter a location and search its timezone by city, IANA name or UTC offset. Verify choices remain valid for the country/city and nothing saves until Confirm location.
2. In the profile selector, open/search near the bottom of a card. Verify the list extends outside the card, options can scroll, keyboard selection works, and resizing/scrolling the surrounding page does not leave an orphaned list. Repeat on mobile.
3. Complete Meta OAuth for a test Company/Project. Check the verified account name in collapsed Step 1, expanded Step 2, unique headings and Meta mark. Confirm no Project route was automatically created by connecting the account.
4. Reopen Step 1 manually, refresh status and check the intended disclosure remains usable. Cancel an authorization attempt or test incomplete permissions: no success claim, no automatic association, and draft values retained.
5. Verify Set up campaigns later is in Step 2 and leaves the Company connected. Explicitly save/verify a test Page/Form route separately before considering Meta lead delivery ready.
6. Recheck an approved public gallery/PDF and a post-onboarding property edit/final approval from deliveries 1/2.

## Commit

```bash
git pull && git add . && git commit -m "Improve timezone search and streamline verified Meta onboarding" && git push
```
