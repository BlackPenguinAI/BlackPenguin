# Project onboarding — Block A

Base: `a9a9056a80d160e14739b8ed5717b3d20eb94dcd` (`origin/main`, group L).
Date: 2026-11-09.

## Delivered behavior

- New Project opens `/app/projects/new`, reusing the existing website welcome component. Opening or leaving this page does not create a Project, profile, chat or extraction job.
- Continue with a valid website, or the explicit no-website choice, calls the new authenticated `POST /api/v1/projects/start` endpoint. The request validates the choice before creation.
- Start creation and chat bootstrap share a transaction. A synchronous bootstrap failure rolls back the new project and its related rows. A later asynchronous extraction failure retains the deliberately started project for recovery through the existing worker/source flow.
- A UUID retry key is retained in session storage while a start is pending or failed, including a lost HTTP response or unsuccessful navigation. The server scopes its deterministic project ID to Company, authenticated actor and key. Changing the website choice for an existing key returns 409. Company-level row locking serializes starts and checks project limits; session locking protects bootstrap. Retries reuse the existing project and initial source/job instead of consuming another project slot.
- Existing `/projects/drafts`, existing draft URLs, onboarding chat and website bootstrap remain supported. No existing draft is deleted, archived or renamed by this delivery.
- Card-bound answers bypass editor task inference. Inventory mentions in descriptive prose are not treated as inventory commands. Explicit inventory and other editor commands remain supported.
- The exact audience from the reported screenshot is persisted without reopening the property catalog. Valid catalog state is preserved.
- The Approve profile button uses the existing explicit completion endpoint. Its answer-recording call now uses the correct service signature. Failed approval refreshes readiness without marking the card answered or redirecting.
- Legacy text approvals resolve against the active question before editor task detection. Replaying an accepted approval turn preserves its overview redirect, without publishing again. Replaying other editor turns does not force users out of a completed chat.
- Successful completion redirects to `/app/projects/{id}`. Existing Project overview and re-entry to the onboarding editor remain available.
- Deferred Meta campaign configuration remains separate from approval and operational readiness. Approval does not fabricate Meta permissions or routing readiness.

## Validation

All results below were obtained before packaging the differential files.

- Focused backend regression: 85 passed (Block A plus editor and onboarding journey regressions).
- Full backend regression: 2103 passed, 4 skipped; final frozen-source run completed in 283.69 seconds.
- Full frontend regression: 442 Angular tests and 9 additional DOM tests passed; 451 total across 86 files.
- Production Angular build: passed. Existing stylesheet budget warnings remain in `agent.scss` and `sales.scss`; these files are not changed.
- `git diff --check`: passed.

Backend execution used isolated test databases and placeholder configuration. Provider/model interactions are mocked; this validation does not send messages, authorize Meta accounts, or deploy changes. The four existing PostgreSQL concurrency tests require a dedicated `DIALOGUE_POSTGRES_TEST_URL` and are skipped without it. Therefore, real PostgreSQL contention and a browser journey against production are not claimed as validated.

Focused checks cover: custom audience with and without a reply ID; edit words in a card-bound answer; text approval with and without a reply ID; approval replay, single publication and redirect recovery; explicit approval, rejection and historical cards; both website choices; duplicate clicks, HTTP failures, navigation failures and page recreation; both SQLAlchemy autoflush modes; one initial source/job on retries; invalid choices; private URL rejection; transaction rollback; Company/actor scoping; role checks; project limits; old draft API compatibility; deferred Meta without activation.

Reproduction:

```bash
# backend/: set the application's required settings to isolated test values.
python -m pytest -q
python -m pytest -q tests/test_project_onboarding_block_a.py tests/test_editor_1316.py tests/test_onboarding_journey_regressions.py

# frontend/
npm run test:sales-ai-k
npm run build
```

## Apply and deploy

1. Update the repository to the base above or review conflicts if later commits touch these files.
2. Extract the differential ZIP into the repository root, preserving its backend/, frontend/ and docs/ paths. It contains complete new/modified files, not a full repository.
3. Review the diff and run the checks above. No database migration, new provider secret or new runtime configuration is required.
4. Deploy the backend before, or together with, the frontend. The new frontend requires `/projects/start`; the updated backend continues to support the previous frontend's draft API.
5. Verify in the deployed environment: abandon New Project before starting; start once with URL and once without; retry a start; submit the reported audience; approve with campaigns deferred; confirm the overview opens; reopen chat from the overview.

Rollback: restore the changed code files to the base revision and redeploy backend/frontend consistently. No schema rollback is needed. Projects deliberately started by this version use ordinary project/session/profile/source/job rows and remain readable by the previous version.

## Scope

This is Block A only. Confirmed-field revision controls, expanded property PDF/gallery editing, duplicate-toolbar removal, contextual defer controls and the Meta accordion redesign belong to Blocks B/C and are not included.

Suggested commit command:

```bash
git pull && git add . && git commit -m "fix(onboarding): defer project creation and resolve review and approval loops" && git push
```
