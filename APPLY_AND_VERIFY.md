# Guided Project Onboarding Finalization

Incremental package prepared on 2026-10-28. Copy the `backend/` and `frontend/`
folders over the repository root, preserving their paths.

## Result

- Separates a 100% Project Profile from final-approval readiness.
- Prevents final approval while sources, extracted proposals, draft lead-sharing
  materials, or consistency conflicts remain unresolved.
- Shows the administrator the exact pending item and keeps the decision receipt
  in onboarding history.
- Presents structured HTTP 409 errors as actionable messages instead of a false
  connection interruption.
- Keeps completed/final-approved status as the gate used by the lead workflow.

No database migration is required by this package.

## Validation performed

- Backend full suite: `452 passed`.
- Focused finalization/material suite: `30 passed`.
- Python compile check: passed.
- Angular production build: passed.
- `git diff --check`: passed.

The Angular test command is currently blocked by unrelated pre-existing spec
imports in the repository (for example `Auth`, `Chat`, and `Toast` test imports,
plus the legacy `ProjectListComponent.newProject` expectation). The production
application build, including the changed onboarding templates and TypeScript,
compiled successfully.

## Administrator verification

1. Open the Project and choose **Continue Onboarding** / **Review pending items**.
2. In **Review file for lead sharing**, choose **Approve for leads** or
   **Keep internal** for every Draft item.
3. Confirm that the decision card remains visible as history.
4. Approve the Project Profile when the final approval step appears.
5. Open Leads and confirm the Project can now be selected for the end-to-end test.
