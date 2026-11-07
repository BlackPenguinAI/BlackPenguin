# Onboarding journey differential — implementation and limitations

Base: `bf6623fc3c13ff7793a3840ef30501d8022de0cd` (origin/main, verified again before packaging).
No push, deploy, live messages, OAuth authorization, migrations or production data corrections were performed.

## Implemented

- Shared plain-question deferral actions are projected inside the AI review bubble. Duplicate Provide later / Configure later actions are suppressed. Final approval no longer shows the generic defer action.
- Deferral UI uses a compact secondary action rather than the detached yellow strip; historical draft receipts have spacing.
- Project cover, catalog and existing-type deferral actions follow the main task.
- Active dedicated Project authorization/team/Meta/location editors no longer also render the redundant generic active AI card.
- Required deferred facts are revisited at the end of the initial Company/Project pass, without approving the saved draft.
- Inventory requests and the legacy catalog shortcut are recognized as editor actions. Explicitly reopening a deferred catalog resumes it without discarding its draft.
- Inventory review explains unknown vs zero, expands types with unknown quantities, and blocks catalog continuation while quantities remain unknown in that review.
- Company team continuation supersedes the previous active question, without sending another invitation.
- Edited extraction proposals use the correction API even when the user clicks the primary Save and confirm action. Separate redundant Save edit buttons were removed.
- Location component owns its styling. City matching prioritizes its IANA zone, supports explicit country-zone alternatives and displays a current date-aware offset. Existing appointments are unchanged.
- Project forms group area min/max/unit, total/available units and prices/currency on desktop.
- Image picking precedes visibility controls. Attachment/later actions precede separate type confirmation; selected unattached images block confirmation.
- Meta uses same-tab authorization; callback redirects back to the Project, retaining popup compatibility. Destination scheme/host/state are checked.
- Composer/new-type/dirty existing-type text drafts are saved locally before Meta navigation and restored on return. Server profile settings remain unchanged until explicit save.
- Meta step 2 deferral is unavailable before account connection. Marketing displays icon/text/colour status badges.
- Marketing deep links open their requested editor after state loads. Reloads return the conversation to its current bottom.
- Operational capability details are collapsed rather than occupying the full sidebar.
- Source extraction prompts request explicit fields and preserve model-address meaning and community-vs-unit scope. Area aliases such as sqft normalize to the selector's ft² without changing the number.
- Embedded Company social links exclude post/reel/video URLs. Company extraction instructions distinguish brands, legal names, DBA and headquarters evidence.
- Communication language suggestions list English only.
- Parking/storage asks for substantive details. An approval/navigation request is recognized before it can be interpreted as a country answer.
- Project overview does not infer sold units from total minus available; address context is deduplicated component by component.

## Automated results

- Backend full suite: **1415 passed, 2 skipped**.
- Focused onboarding/frontend regression: **188 passed**, 18 files.
- Angular production build: passed; existing style-budget warnings in agent.scss and sales.scss remain.
- git diff --check: passed.
- No production E2E or browser screenshot validation was performed.
- The default npm test command is NOT green: old scaffold specs contain invalid imports.
- The old project-chat.spec.ts also has pre-existing failures: reproduced separately on an unchanged bf6623f worktree (**33 failed, 1 passed**). The focused command excludes that file explicitly; this is not a claim that all frontend tests pass.

Run:
```bash
cd frontend
npm ci
npm run test:onboarding
npm run build
```
Backend: run `python -m pytest -q` in backend using the repository's test environment, never production credentials.
The logs included under delivery are from local runs with synthetic credentials and mocked provider interactions.

## Still open — do not treat the entire original plan as completed

1. Full date/scope modeling for Project, phase, property type and individual-unit delivery dates is not implemented.
2. Cross-role Project Sales eligibility has NOT been expanded. Existing explicit Sales capabilities and access controls remain in force. Do not automatically grant Marketing users Sales permissions.
3. Complete server-persisted multi-selection drafts across Provide later/resume remain to be implemented; the existing typed answer contract is unchanged.
4. Dedicated detail collection for each compliance category, a full structured parking/storage editor, comprehensive Company contact validation improvements, legal-name/DBA/HQ extraction heuristics, and a complete source-by-source provenance UI are not closed by this patch.
5. Extraction coverage improvements are prompt/normalization changes, not proof that a live website or every PDF will produce all fields. Existing saved quantities, prices and areas are not retroactively rewritten.
6. Complete visual standardization across every source/logo/material card and real laptop/mobile browser QA remain pending.
7. Same-tab Meta success, cancel, provider error and permission revocation need a real authenticated acceptance run. Local text drafts are restored, not browser-selected upload File objects.
8. No Sales AI conversation/runtime changes or proof of how it consumes qualification/compliance settings are included.

## Manual acceptance before considering the full onboarding closed

- Start a new Company; review extracted edited fields, contact channels, location and an existing team without another invitation.
- Confirm country requests cannot capture approval/navigation text.
- Create a Project; verify explicit sqft area renders ft² and correct its current source evidence.
- Confirm catalog with unknown availability, finish other questions, then verify availability editor returns without a loop.
- Test 0 available separately from unknown, save every type and reach final review.
- Pick images, choose visibility, attach or defer, then confirm the type; verify no lead-sharing permission is granted.
- Authorize Meta in the same tab, return to the correct Project at the bottom, discover assets, and either save/verify or defer step 2.
- Check Marketing badges, approved profile vs operational readiness, and edit/reapprove the profile.
- Validate laptop and mobile manually.

Ashville Park data requiring human review: saved 3734 m² vs source 3734 sq ft; concatenated street/city input; whether 114 is a Project total or this type's total; and source/date of availability 1. These were not modified in production.

## Applying

Pull the base first and ensure your local tree is clean. If origin/main differs, rebase/review instead of overwriting blindly.
Copy backend/, frontend/ and docs/ from this archive to the repository root. delivery/ contains evidence/instructions, not runtime files.
No dependency versions or DB schema were changed. Keep frontend/package-lock.json as-is.
Use delivery/manifest.json to check paths and original/new SHA-256 values.

Rollback: restore only this manifest's paths from the base commit after backing up any later edits. No destructive reset command is required.

