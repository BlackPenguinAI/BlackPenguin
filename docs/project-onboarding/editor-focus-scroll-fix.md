# Project onboarding: one active editor and contained workspace scrolling

Baseline: `00fc9ac9028f4f3df275ef3dcded2dd8f83f011c` (delivery 3).
Apply the ZIP's differential files at the repository root.

## Navigation behavior

All eight shortcuts use the same server-coordinated editor transition, including Property types. A successful switch closes the previous interactive editor, highlights the current shortcut and focuses the new review inside the conversation scroll container. Old questions remain history, with superseded controls inactive.

- Existing unchanged values and approval remain intact.
- An empty section is recorded as pending for later in UI metadata.
- Modified inputs are stored as unapproved drafts; reopening restores them using the existing draft mechanism. This includes property fields/new types, gallery-access choices, structured location/delivery/parking and Meta form values.
- Fields previously resolved as Not applicable remain resolved when left unchanged.
- Navigation does not promote drafts to Project facts, publish a revision, grant lead access, assign Sales, associate Meta assets or activate delivery. Account and campaign deferrals are separate in these transitions.
- A current save finishes before navigation. The last requested target wins during rapid clicks. A failed save or switch keeps the current editor available; failed destination opening rolls back the entire transition.
- Navigation uses a revision check for competing sessions. Retries of the same unchanged operation reuse their idempotency key, including a lost response after a server commit.
- Selected but unuploaded browser files are retained: switching asks the user to upload or remove them first. Files are never discarded or automatically sent just to navigate.
- Confirming location finishes that editor and returns to the guided review. Catalog confirmation closes its editor. A Return to guided onboarding action resolves an unfinished review as above without approving it.

UI metadata uses the existing __ui_deferrals__ bag, including __editor_focus__. It is excluded from commercial snapshots. Existing clients can still use the editor endpoint without the optional transition object. No schema migration, production dependency or environment setting is added.

## Scroll/layout behavior

The Project onboarding route gets a bounded 100dvh workspace. The outer application main area does not own scrolling on this route; the conversation and review-panel body scroll independently. Header/composer/panel footer do not shrink into the middle of a long page. Flex ancestors have explicit zero minimum height.

Task navigation and blocker navigation adjust only the conversation's scrollTop. Ancestor-scrolling scrollIntoView calls were removed from the Project chat. The current editor receives focus with preventScroll.

The review sidebar is a drawer below 1280px, leaving adequate conversation width on tablets. On phones below 768px, the outer application sidebar is hidden only on Project onboarding; the existing back-to-Projects control remains available. Other application routes retain their normal outer-page scrolling.

## Verification

- Backend: **255 passed**, including atomic rollback, unchanged approval/snapshots, empty/modified drafts, reopening, independent Meta deferral, idempotency, stale navigation, credential/foreign-property rejection and previous onboarding/resource regressions.
- Frontend: **312 passed / 32 test files**, including rapid clicks, one active task, failed-switch retention, same-key retry, structured draft capture, in-flight saves and route-specific layout classification, plus previous delivery regressions.
- Production/offline-CI Angular build passed. Existing agent.scss and sales.scss size warnings remain.
- Browser script syntax checked. Actual Chromium verification could not run: the environment denies the process-singleton socket (`Operation not permitted`), including a single-process/no-zygote launch attempt. DOM tests do not prove pixel geometry; native scroll/composer verification remains pending.
- No production mutation, live provider call or lead message was performed.

## Reproducible browser check

`frontend/tools/project-onboarding/editor-browser.cjs` serves the compiled local build, mocks all API responses, blocks external traffic and tests the eight shortcuts at 1440, 900 and 390 pixels. It checks one active task, composer alignment with the viewport, zero outer-main scrolling and absence of an oversized document. It never uses production data.

In a QA environment with Playwright and Chromium available:

```bash
cd frontend
npx ng build --configuration production,offline-ci
BP_CHROME=/usr/bin/chromium node tools/project-onboarding/editor-browser.cjs
```

## Production smoke check

1. Before onboarding completion, open each shortcut and then another. Check only the new section is interactive; empty previous sections appear pending for later.
2. Repeat on an approved Project. Leave filled sections unchanged and confirm no new commercial revision/approval is created by navigation alone.
3. Type a location, delivery/parking entry, new property without a name and an existing property change. Switch, reopen and reload; the saved draft must remain unapproved and available. Save explicitly, then check pending-draft status clears.
4. Click several shortcuts rapidly and simulate a network/save failure. Check the last selected destination wins after successful completion; errors leave entries available and a retry does not duplicate the turn.
5. Scroll long history and expanded reviews at desktop/tablet/phone sizes. The chat composer must remain at the bottom of the workspace, without the second screenshot's outer-page jump or blank region. Check drawer focus and back navigation.
6. Confirm location/catalog, finish current approval and return to the Project summary. Recheck public PDFs/galleries and Meta account/campaign independence.

## Commit

```bash
git pull && git add . && git commit -m "Fix onboarding section transitions and contain workspace scrolling" && git push
```
