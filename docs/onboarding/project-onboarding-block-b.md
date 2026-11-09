# Project onboarding — Block B

Base: `d11b2ab04277930936438661916fbc1230b09784` (`origin/main`, Block A).
Date: 2026-11-09.

## Delivered behavior

### Confirmed source fields

Confirmed and previously corrected Project proposals both offer Edit, Save revision and Cancel. Saving validates the value, records the reviewer and revision, and retains the original source, evidence and review history. The UI supplies the proposal revision; a stale save returns 409 instead of overwriting another revision. Proposal and profile changes commit together. Published commercial facts remain unchanged until explicit Project profile approval. Routine polling preserves an open editing draft and its original revision.

### Reusable property catalog

Property types opens the existing catalog in the onboarding chat without posting a new chat turn or superseding the active question. Administrators can select a property type, edit it, add another, remove a type through the existing confirmation, and return to the conversation. The same controls work during onboarding and after reopening a completed Project's chat.

Property receipts and material-review messages preserve a still-valid pending question and its reply ID. Deferred/resumed cards continue to use their existing recovery path, including their saved selections. Changing genuinely dependent facts may still require the appropriate review; unrelated answers are not consumed by opening the editor.

### Photos and lead gallery

Attached images can be removed independently of unsaved scalar details. Original source files and audit history are retained. Published profile snapshots now include property-media membership, so a media edit becomes a draft instead of silently changing an approved profile.

Save gallery access is an explicit permission decision for the currently attached images. A stale image selection returns 409. An approved gallery is an encrypted, self-contained HTML snapshot with embedded validated images, escaped labels, no scripts, no remote requests and no private source URLs. Its public response uses a restrictive CSP sandbox and no-store caching.

One sales-asset identity is maintained per property gallery. Saving the same approved selection again is idempotent. New selections update that resource's version and URL. Adding/removing images invalidates the old gallery until the administrator reviews the new selection. Turning access off, removing a photo or removing the property revokes affected lead links; gallery regeneration never silently adds unreviewed images to an earlier approved snapshot.

### Property PDFs

Each saved property card accepts multiple PDFs, including documents containing plans, photos and other information. The administrator declares their content categories and explicitly chooses whether each PDF is accessible to leads. Internal is the default. The upload validates size (15 MB), MIME and readable, unencrypted PDF structure before registering a resource. Uploading a property document does not automatically overwrite Project facts.

The card supports authenticated preview, allowing/revoking lead access and removing the PDF association. Removing a PDF revokes its issued links and retains its original source privately for history. Removing an association does not delete original onboarding evidence or unrelated property files.

### URLs and Sales Agent compatibility

Approved local resources expose an opaque signed capability URL. It is usable by a recipient who has the URL while that exact resource version remains approved and valid. It does not grant access to other properties or internal files. The URL changes with the approved version/source, and stops resolving after access is revoked. These links are intentionally recipient-accessible; authentication is still required for internal source downloads and management.

The Sales Agent continues using the existing approved-material selection and per-lead short-link issuance, expiry, delivery bindings and access tracking. Gallery responses are rendered through that existing share endpoint too. Editing/archiving an asset revokes its outstanding per-lead links and records the current authenticated revoking actor when available. It does not attribute the revocation to the original approver. Legacy links with asset IDs also recheck current approval, targeting, channel and validity before serving content. No live messages or provider permissions are issued by this delivery.

## Validation

- Focused backend regressions: 58 passed (Block B, existing deferred-answer recovery and sales assets).
- Final full backend suite: 2123 passed, 4 skipped; 288.78 seconds.
- Final full frontend suite: 464 passed (455 Angular tests plus 9 additional DOM tests).
- Production Angular build: passed; only existing stylesheet-budget warnings in agent.scss and sales.scss remain.
- `git diff --check`: passed.

New backend checks exercise actual PNG/PDF bytes, proposal revisions and stale saves, unchanged published snapshots, selected-image-only gallery HTML, CSP/escaping, file-integrity rejection, idempotent gallery updates, version rotation, canonical and per-lead link revocation, internal-by-default PDFs, multi-content PDF declarations, property/document removal, cross-property/cross-Company isolation, role restrictions and active-question continuity.

New frontend checks exercise catalog opening without a chat write, property selection, editing/cancel of confirmed values, optimistic revision transport, stale-save recovery, polling preservation, independent image removal, explicit gallery/PDF choices, authenticated preview before history reload, document removal and actual Angular DOM rendering of the Edit and property-resource controls.

The existing four PostgreSQL concurrency tests require `DIALOGUE_POSTGRES_TEST_URL` pointing at an isolated database and are skipped without it. SQLite tests do not establish real PostgreSQL contention behavior. Browser-based production acceptance and a live LLM/provider run are not claimed. All automated tests use isolated data and mocked providers; production was not changed.

Reproduction:

```bash
# backend/ — supply the application's required settings with isolated test values.
python -m pytest -q
python -m pytest -q tests/test_project_onboarding_block_b.py tests/test_onboarding_followup_drafts.py

# frontend/
npm run test:sales-ai-k
npm run build
```

## Apply and deploy

1. Update the repository to Block A or review later changes against the base commit above.
2. Extract the differential ZIP at the repository root, preserving backend/, frontend/ and docs/ paths. It contains complete new/modified files, not the whole repository.
3. Review the diff and run the checks. No database migration or new runtime setting is required. Existing encrypted storage and signing configuration are reused.
4. Deploy the backend before or together with the frontend. The new frontend requires the resource/gallery/document endpoints. Existing draft, chat, material and Project-overview APIs remain available.
5. In the deployed environment, verify an existing completed Project and an in-progress one: Edit/Cancel a confirmed field; select and update a property; add another; attach/remove a photo; publish a gallery; change its selection; add an internal and an accessible PDF; revoke each URL; return to the pending chat question; approve the updated profile and reopen its overview.

Rollback: before reverting the backend, keep affected property resources internal to revoke their issued links while Block B is available. Restore these code files to the base revision and redeploy backend/frontend consistently. No schema rollback is needed. Source files and ordinary sales-asset records remain stored; the previous backend does not render the new generated-gallery MIME as a gallery page.

## Scope

This is Block B. Block A is the base and its start/approval behavior is preserved. Duplicate-toolbar cleanup, the general contextual defer-button redesign and Meta accordion changes remain in Block C.

```bash
git pull && git add . && git commit -m "feat(onboarding): add confirmed field editing and shareable property resources" && git push
```
