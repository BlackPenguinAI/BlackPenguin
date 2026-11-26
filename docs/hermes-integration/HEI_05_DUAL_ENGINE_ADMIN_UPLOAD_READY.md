# HEI-05 — Dual Engine Admin Panel

Base commit: `20f89051ef8c62832613b9e9530f079b1c47025d` (HEI-04).
Verified successful deployment: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45877007064.

Commit: `feat(hermes): add guarded dual-engine administration and selection review`

## Upload Ready

Extract this differential and upload the complete files to the repository root, preserving paths. No scripts, patches, migrations, credentials or new runtime variables are required. The existing hidden `.github/workflows/hermes-sdk-smoke.yml` remains absent on the verified base; the unchanged independent smoke workflow from HEI-04 is included as a separate optional upload. Verify that the file appears at the expected path and run it. It is not a live certification.

## Administrative experience

- Staff Superadmin only. `/admin/ai-settings` opens the legacy editor inside a thin shell that includes the global routing control. The original legacy and onboarding components and templates are unchanged: the 10-stage workflow, segments, scoring, cadence, intent routing, protocol, guardrails and version history are retained. Choose Sales Agent in the legacy editor to edit its Sales configuration.
- `/admin/ai-settings/hermes` opens the independent Hermes policy editor and the same routing control. Provider, English language, approved model list, system prompt, iteration limit, tool allowlist, enabled flag, draft, publish and restore remain available even when Hermes cannot be selected. Historical publications are labeled separately from drafts. Changing the global engine does not discard unsaved local Hermes edits; publish/restore reload the published policy. Navigating between editors can discard unsaved local edits; save a draft first.
- Status distinguishes selected engine, effective routing, target default, backend readiness, published policy and model, policy validity, policy enabled flag and actual selectable engines. Effective routing is not an operational health check. `live_hermes_ready()` is unchanged and returns false; Hermes is not selectable. Publishing an enabled policy does not enable live Hermes. No automatic fallback or automatic selection occurs.
- The selector requires a nonempty reason and explicit global confirmation. It uses the existing `GET /api/v1/ai/hermes/engine` and `PUT /api/v1/ai/hermes/engine`; the latter receives `active_sales_engine`, `change_note`, `expected_revision` and `expected_published_version_id`. Compare-and-set is verified under the existing settings row lock. Stale requests return HTTP 409 `ENGINE_SELECTION_STALE`; the UI clears the reviewed change and refreshes status, without retrying PUT. Existing callers that omit the optional snapshot fields retain the existing API contract. No production engine changes were made. A genuine future switch remains audited in existing Hermes global versions; the existing router continues pinning events and no legacy settings are overwritten.
- Publication validation is projected only for the admin endpoint, not on the runtime hot path. If the saved policy does not match its current published version, Hermes cannot be selected even in a readiness-enabled test double. This projection does not change the runtime readiness gate. Actual provider/worker connectivity, runtime-health certification, active Hermes policy behavior under future administrative changes, and concurrency on PostgreSQL are HEI-06/07 verification items.

## Validation

The original `staff_config.py` (a731b34482dea5b81de79643c05d7d92ceffe613), `engine_staff_router.py` (03edec609c73d0b76b0eeb2803c4e30897598c13), and `app.routes.ts` (d332ae8db76b63080fa4af19e19786a6f26db3a0) were checked against the Git blobs in the deployed base. The route change is limited to the legacy editor shell; the existing guarded admin route and Hermes route remain intact. The Hermes editor was rewritten from the current fetched source, retaining its policy fields and operations.

Backend: 14 new cases and 304 previous HEI cases passed locally in three groups (217 + 38 + 63 = 318). The local environment uses the extracted HEI-04 predecessor image and HEI-04 overlay from the prior work, Python 3.12.16, SQLite and synthetic values; the modified original backend files match the current commit. The initial real-ORM regression run lacked required environment variables and failed during setup; rerunning with isolated synthetic settings passed. The selection endpoint tests reuse the HEI-01A fixture with actual settings/version ORM models and a role dependency double; not a production auth or PostgreSQL concurrency test. Future-ready test doubles never change the shipped gate. No real provider, model or Calendar calls were made, and the full application suite was not run.

Frontend: all five changed/new TypeScript files passed syntax transpilation. Offline class checks with mocked decorators and HTTP observables passed for blocked selection, confirmation/CAS, stale refresh, preserving editor changes and separate draft/publication. Ten Angular/Vitest tests are included but were not executed locally; Angular dependencies are unavailable. The full Angular build, tests, actual visual rendering and route/navigation checks remain mandatory in CI/deployed review.

## Manual acceptance after deployment

1. Open AI Settings as Staff Superadmin. Confirm LangGraph selected/effective, Hermes as target, Hermes button disabled and reason visible. Do not attempt to force activation.
2. Click the legacy Sales Agent tab. Verify the existing stages, segments, intent, scoring, cadence, prompts and history remain editable. Open Company/Project Onboarding tabs and verify they are unchanged.
3. Click Hermes settings. Confirm the published model, prompt, tools, iteration and policy enablement are editable while routing stays blocked. Save a draft if desired; verify the registry/history and routing separately. Do not publish a change to the current production policy merely to test the UI unless authorized.
4. Refresh status from each editor. Confirm both show the same server routing and that a failed request does not enable selection. Check unauthorized tenant accounts are denied by the existing route and API protections.
5. Verify the normal deployment workflow, focused frontend tests and independent SDK smoke workflow. Do not activate Hermes until HEI-06 evaluation and HEI-07 controlled rollout are approved.

## Next

HEI-06 — End-to-End Evaluation: run actual pinned Nous Research SDK, certify private runtime connectivity with staged isolation, evaluate conversational parity against the Vercel demo, exercise provider/Calendar receipts and rollback, test cross-engine and uncertain execution boundaries, and record remaining P0 blockers before production cutover.
