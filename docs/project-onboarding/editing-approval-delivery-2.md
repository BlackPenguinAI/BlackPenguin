# Project onboarding — Delivery 2: stable editing and current approval

Baseline: `9986c7451ed617676614db801124d65a023afdc2` (public resources delivery 1).
Apply the ZIP's differential files at the repository root after that baseline.

## Behavior

- Property cards, message rows and property resource rows are tracked by persistent ID. Refreshing server data does not recreate the property editor, reset its disclosure, discard dirty scalar fields or move focus into a new control.
- Property disclosure is controlled separately from saved/confirmed status and updated_at. Saving a property keeps its card open.
- Saving/revoking a PDF's lead access updates the material and readiness separately from property details. It displays a confirmation and does not require another PUT of unchanged property fields. Pending material loads cannot override a later explicit approval/revocation response.
- PDF controls are recognizable buttons. A divider and spacing separate Property PDFs from Photos and lead gallery. Approved PDF/gallery links from delivery 1 remain public and unchanged.
- Unchanged confirmed property details show Property details saved; saving permissions does not enable an unnecessary property-details save.
- Gallery-access changes must be saved, and selected images attached or deselected, before confirming the catalog.
- Confirm catalog and continue closes that editor only after success and synchronizes/scrolls to the current review at the bottom.
- Historical final-approval messages remain read-only, retain their original timestamps/content and cannot call approval. There is one current review after the active editors and blockers.
- Approval is disabled during outstanding saves/synchronizations, unfinished catalog editing, unsaved local changes, pending uploads or unresolved material decisions.
- The current action submits expected_revision. The backend checks it after obtaining the existing profile-edit lock and before publishing. A stale revision returns 409 and refreshes the current review without navigation or publishing the unseen draft.
- New approvals have a new immutable receipt with the published revision. An old unanswered approval prompt is marked superseded rather than presented as acceptance of an earlier draft. Existing answered history is preserved.
- Successful approval returns to the Project summary. If the profile is already approved and only material access changed, the current review offers Return to Project summary instead of requesting another profile approval.

## Compatibility and boundaries

No schema migration, new environment variable or dependency. Existing empty-body completion requests retain their readiness/authorization checks for backward compatibility; the updated UI supplies the revision. Previously published Project facts continue to be used until new profile changes are approved. Material access remains a separate explicit decision.

Location/timezone search and the Meta connection accordion remain delivery 3.

## Validation

- Backend: **203 passed** across current-approval, previous project onboarding, draft/published revisions, lossless answers, public resources and catalog suites.
- Frontend: **293 passed / 27 test files**, including the existing Project chat suite plus onboarding, catalog/media, marketing, public-resource controls and Project summary regressions.
- Production/offline-CI Angular build passed. Existing agent.scss / sales.scss stylesheet-budget warnings remain.
- No production write, live lead delivery or real-browser walkthrough was performed. Editor identity/focus, disclosure, read-only history and current-review ordering were verified in rendered Angular DOM tests. Native viewport/scroll behavior remains a production smoke check.

Backend command (with the usual test environment):

```bash
cd backend
python -m pytest tests/test_project_current_approval.py tests/test_project_onboarding_block_a.py tests/test_project_onboarding_block_b.py tests/test_onboarding_revisions_and_money.py tests/test_onboarding_lossless_answers.py tests/test_public_property_resources.py tests/test_catalog_789.py -q
```

Frontend command:

```bash
cd frontend
npx ng test --watch=false --ts-config=tsconfig.onboarding-regression.json --include='src/app/pages/client/projects/project-chat/*-*.spec.ts' --include='src/app/pages/onboarding-*.spec.ts' --include='src/app/shared/ui/onboarding-*/*.spec.ts' --include='src/app/shared/ui/configure-later/*.spec.ts' --include='src/app/shared/ui/public-resource-link/*.spec.ts' --include='src/app/pages/client/projects/project-overview/*.spec.ts' --include='src/app/pages/client/marketing/*.spec.ts' --include='src/app/core/timezones.spec.ts'
npx ng build --configuration production,offline-ci
```

## Production smoke check

1. Reopen an approved Project and edit Property types. Open a saved type, change its description without saving, then approve/revoke a test PDF's lead access. Check the same card remains open, the description remains typed, and the selected property/focus/scroll remain usable.
2. Check the PDF section divider, button presentation, explicit material-access confirmation and public Open/Copy link actions. With no property-field edits, Property details saved should remain disabled.
3. Save property changes and confirm the catalog. The latest final review must be below the new receipts. All old approval prompts must be read-only.
4. Approve the pending revision and confirm return to the summary. If only material access changed and the profile remains approved, use Return to Project summary without another approval.
5. Open the pending revision in two sessions. Save a profile edit in the second session, then approve from the stale first session: expect a revision-conflict message and refreshed review; no silent publication. Review and approve the refreshed revision to finish.
6. Reload while changes are pending and verify the current review is reconstructed at the bottom without reactivating historical controls. Check desktop and mobile scroll/focus.

## Commit

```bash
git pull && git add . && git commit -m "Preserve project editing state and approve the current profile revision" && git push
```
