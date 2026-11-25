# BlackPenguin Hermes — P05 + P06 (Entrega 4)

**Repository baseline:** `BlackPenguinAI/BlackPenguin` `main` at `c4e6551375eecd787e3da1f84f3d01971b8fe4a6` (the P04 CI hotfix).

## Scope

1. **Global Staff configuration** at `/admin/ai-settings/hermes`, linked from the Staff dashboard.
   - One configuration across all Companies and Projects. No per-Company, per-Project or per-Lead overrides.
   - English (`en`) only. OpenRouter only. `hermes-agent` only.
   - Staff controls allowed model slugs, selected model, main system prompt, maximum Hermes iterations (1–12), tool allowlist, and a staged enable flag.
   - Draft, publish, browse and restore a global version without deleting history.
   - No API credentials stored in version records. The future runtime reads `OPENROUTER_API_KEY` from server environment.
2. **Staff diagnostics** under the existing `/monitor` interface.
   - Select Company → Project → Lead → Conversation using existing filters.
   - View scoped Hermes phase, focus, primary/temporary preferences, visit draft, choice-set summary, revisions and operation receipts. No private model reasoning or bearer share URLs.
   - This route uses the existing Staff Superadmin checks and audited monitor access.
3. **Shared Agent/Schedule context**: the existing `app-agent-context` component now exposes an opt-in, read-only **View Hermes state** control.
   - Agent has `conversationId`; Sales/Schedule has `meetingId`. When a meeting can reference multiple conversations, no lead state is guessed.
   - Tenant endpoints reuse BlackPenguin's existing `scoped_conversation` and `meeting_context` policies including project and Sales-user access.
   - Leads retains its existing navigation into Agent. No extra lead-specific settings are created.
4. **Additive Alembic migration** creates `hermes_global_settings` and `hermes_global_versions`. No prior Sales tables are dropped, rewritten or migrated.

## API

Mounted under `/api/v1/ai/hermes`:

| Route | Method | Permission |
|---|---|---|
| `/global` | GET | Staff Superadmin |
| `/versions` | GET | Staff Superadmin |
| `/versions/{id}` | GET | Staff Superadmin |
| `/drafts` | POST | Staff Superadmin |
| `/versions/{id}/publish` | POST | Staff Superadmin |
| `/versions/{id}/restore` | POST | Staff Superadmin |
| `/staff/conversations/{id}/context?company_id=...&project_id=...&lead_id=...` | GET | Staff Superadmin + audited selection |
| `/conversations/{id}/context` | GET | Scoped Company roles via existing operational access rules |
| `/meetings/{id}/context` | GET | Scoped Company roles via existing meeting access rules |

The API exposes no runnable conversation endpoint or booking action.

## Important boundaries

- Publishing an Hermes version **does not replace LangGraph** in live messaging; the P08 production cutover is still required.
- Until cutover, the legacy *Sales Agent* tab in the existing AI Settings remains for compatibility with the old engine. It is **not the Hermes configuration**; use **Hermes Sales Core** from the Staff dashboard instead. Remove the legacy editor only with P08's reviewed dependency cleanup.
- The Staff enable flag is staged policy data. It does not itself enable SMS/WhatsApp sends, Google Calendar writes, queue routing, or an SDK worker.
- The runtime has an opt-in `settings_for_turn` resolver for a future isolated worker. It does not override any platform permissions, and the future worker still must enforce the enabled toolset at the SDK registry boundary before P08.
- Permission, consent, opt-out, inventory approval, confidential prompt isolation, transactional booking and idempotency must stay in backend code. Admin prompt/tool edits must not bypass them.
- No Company or Project onboarding shape is changed. Their data is passed as *context*, not settings.

## Validation performed locally

- 155 previous P01–P04 tests passed using differential ZIP reconstruction, including the P04 CI hotfix.
- 15 additional P05 tests passed with SQLAlchemy/SQLite (global scope, validation, draft/publication/restore, missing version, migration upgrade/downgrade).
- **170 Python unit/regression tests passed in total** in the reconstructed differential environment.
- New Python modules pass `compileall`; changed TypeScript files pass the TypeScript transpile syntax checker.
- The complete Angular production build, full GitHub CI suite, PostgreSQL migration on staging, OpenRouter SDK, actual calendar/provider integrations and end-to-end UI were **not** run in this environment. Those are release acceptance items, not proven passes.

## GitHub upload and deployment notes

1. Unzip the archive locally. Upload the **full directory content**, keeping repository-relative paths (`backend/...`, `frontend/...`, `docs/...`). No patch runner or local script is needed before upload.
2. **Use a GitHub integration branch / PR first**. In this repository, publishing to `main` starts DigitalOcean deployment; changes under `backend/app/db/` and `backend/alembic/` trigger `alembic upgrade head` automatically.
3. Check backend pytest shards, Angular production build, migration upgrade on a disposable/staging PostgreSQL instance, and API role enforcement before merging.
4. In Staff Dashboard, open **Hermes Sales Core · Global settings** and verify draft → publish → reload → restore. Try a non-Staff account: it must receive 403.
5. In Staff Monitor, select one real conversation and confirm the Hermes panel shows **No Hermes state** if P04 has not been used there; no synthetic state should be invented. In Agent/Schedule, open read-only Hermes context and verify scoped access.

## Remaining gates before cutover

P07: full PostgreSQL and Angular E2E, OpenRouter runtime, isolation/concurrency, arrival ordering, version pinning, prompt/tool policy enforcement, idempotent real booking and share receipts, SMS/WhatsApp provider acceptance and delivery paths. P08: replace legacy commercial dispatch, remove obsolete LangGraph commercial code and controls, and complete production activation only after P07 gates pass.
