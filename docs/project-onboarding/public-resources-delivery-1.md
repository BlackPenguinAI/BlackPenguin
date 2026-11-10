# Project onboarding — Delivery 1: public resources

Baseline: `e609ac4` (Sales delivery 5). Apply these differential files at the repository root.

## Result

- Approved property galleries and PDFs open in a new tab without a user login or Bearer token. Their HMAC signatures, approval, availability, target coverage and version checks still apply.
- Onboarding and the Project summary show the public URL, an open action and Copy link. Only unavailable/internal resources retain the authenticated source-preview action; the summary limits that action to editors.
- An approved gallery shows the published Project name, the snapshotted property name, Available images, thumbnail grid and a native modal with previous/next, keyboard arrows and Escape. Layout supports mobile. The modal contains only approved embedded raster images.
- Previously stored galleries receive the new presentation when read; their stored bytes, approval timestamps, versions and existing URLs do not change. New pending images are never added by the renderer. No backfill or reapproval is required.
- Invalid, expired, revoked, removed or corrupt public resources return HTTP 404 with a friendly unavailable page and no caching. Unicode/malformed signatures also fail closed.
- The Sales Agent keeps its existing short tracked URLs and access events. They render the same resource content as staff's public links; staff opening a reusable URL does not manufacture a lead access event. External virtual tours continue to work.
- Overview status normalizes approved_targeted as approved for presentation, retaining backend coverage validation.

## Boundaries

No schema migration, new production environment variable, external gallery dependency, production data mutation or messaging change. Resources remain tied to reviewed targets. Uploading a file alone does not publish it. Public read permissions do not expose authenticated source-file or management endpoints.

The location selector, Meta accordion, editor persistence, PDF-action restyling/divider and current final-approval placement remain scheduled for deliveries 2/3.

## Validation

- Backend: 276 passed across public-resource HTTP/middleware tests, property resources, sales assets, material coverage, Sales material delivery, catalog and prior onboarding regressions.
- Frontend: 248 passed across onboarding regressions, shared link controls and Project summary tests. Targeted public-resource controls also passed separately.
- Generated gallery JavaScript: DOM checks passed for thumbnail opening, previous/next wrapping, keyboard navigation and closing.
- Production/offline-CI Angular build: passed, with existing agent.scss and sales.scss size warnings.
- Real Chromium acceptance: not run successfully in this environment. Chromium exits because its process singleton socket is denied (`Operation not permitted`). The repeatable local-only browser check is included at `frontend/tools/public-resources/browser.cjs`; it tests actual CSP headers, image decoding, modal navigation, native Escape/focus restoration and desktop/mobile overflow. Requires Playwright/Chromium plus backend Python dependencies. No production site or real lead is contacted.

Commands (with the usual backend test environment configured):

```bash
cd backend
python -m pytest tests/test_public_property_resources.py tests/test_project_onboarding_block_b.py tests/test_sales_assets.py tests/test_sales_delivery3.py tests/test_sales_ai_group_e.py tests/test_catalog_789.py tests/test_project_onboarding_block_a.py -q
```

From frontend:

```bash
npm run test:onboarding -- --include='src/app/shared/ui/public-resource-link/*.spec.ts' --include='src/app/pages/client/projects/project-overview/*.spec.ts'
npx ng build --configuration production,offline-ci
BP_PYTHON=/path/to/backend-venv/bin/python node tools/public-resources/browser.cjs
```

## Production smoke check after deployment

1. Open an existing approved gallery and PDF from the property editor and Project summary in a private browser window: no sign-in prompt; PDF inline; gallery titles, thumbnails and navigation visible.
2. Copy each URL and open it on a phone. Confirm PDF behavior according to the browser's native PDF support; mobile browsers may offer their native download/open-file option.
3. Revoke access on a test resource: its previous reusable and lead-tracked links must show Resource unavailable. Repeat for a deleted test property type and a material covering a deleted test unit.
4. Confirm an internal-only PDF has no public URL and its authenticated source endpoint still rejects anonymous access.
5. On a test lead conversation, request the approved resource and open the generated tracked link; verify delivery/access history. No real delivery was performed during local validation.

## Commit

```bash
git pull && git add . && git commit -m "Fix public project PDFs and galleries with direct share links" && git push
```
