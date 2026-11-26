# HEI-01A — Engine Selection & Routing (Upload Ready)

**Base:** `BlackPenguinAI/BlackPenguin` main `b6f268bbf5fae7d589e5639bdb5777be4cbb2f0c` (P09.1).

**Commit:** `feat(sales): add guarded dual-engine selection and routing`

**Scope:** HEI v4.1, HEI-01A only. This is the guarded selection and routing foundation, not a live Hermes cutover. No database schema changes, migrations, dependency changes, prompt edits, onboarding redesign, hard deletion, infrastructure redesign, or direct provider operations are included. No repository or production system was modified in preparing this ZIP.

## 1. Upload

Extract the ZIP and upload its **contents** to the repository (preserve the `backend/` and `docs/` paths). The archive contains complete replacement files and new files only. Do not apply a patch or execute a script before upload. The normal `main` workflow builds/tests and then deploys the candidate if its gates pass. Prefer a review branch if available; otherwise use the established main upload flow and monitor CI. Do not manually alter the production database or change any flag to enable Hermes.

## 2. What ships

| File | Status | Change |
|---|---|---|
| `backend/app/modules/hermes_sales_core/engine_selection.py` | New | Explicit `hermes` / `langgraph` selection, readiness gate, compatibility with missing key, no automatic fallback |
| `backend/app/modules/hermes_sales_core/engine_staff_router.py` | New | Staff Superadmin-only selection/status API; 409 while Hermes live is not ready |
| `backend/app/modules/hermes_sales_core/staff_config.py` | Modified | Selector stored in existing P05 JSON; independent of `enabled`; explicit switch audit; prompt draft/publish/restore cannot implicitly switch engines |
| `backend/app/modules/ai_core/router.py` | Modified | Mount only the additional Staff API; existing configuration endpoints retained |
| `backend/app/modules/sales_agent/engine_router.py` | New | Deterministic route selection and opportunity/event pin; reuse claimed job and existing handler; review instead of fallback |
| `backend/app/modules/sales_agent/live_worker.py` | Modified | Route claimed inbound and scheduled jobs (cadence/resume/inactivity) at the worker boundary |
| `backend/app/modules/sales_agent/current_simulation.py` | Modified | Explicit engine resolution before execution of the existing UI simulator; retain isolated P08 runner |
| `backend/tests/test_bp_hei01a_engine_selection.py` | New | Hermetic selector, versioning, API and claimed-job regression tests |
| `docs/hermes-integration/HEI_01A_UPLOAD_READY.md` | New | This delivery and acceptance guide |

## 3. Current state vs final target

- **Current deployed behavior after a successful HEI-01A release:** legacy LangGraph remains operational. Pre-HEI rows without `active_sales_engine` resolve to `langgraph`, even if P05 `enabled=true`.
- **Final target:** Hermes is the default when the production runtime and real effects have passed HEI-01B/03/06 readiness. LangGraph remains an explicit alternative. Legacy configuration remains intact; no existing admin UI is removed.
- The phase adds the API and persistent selection contract; the visible switch/engine-aware admin UI is HEI-05. This release does not pretend that a click or API response makes the SDK production-capable. `live_hermes_ready()` is deliberately false and not an operator-controlled feature flag. Selecting Hermes via the API returns HTTP 409; an invalid or unavailable stored engine does not silently become LangGraph.
- P08 is still an isolated simulation runner; the existing simulation guard must not be removed to obtain live effects.

### Staff API

Under the existing API prefix, e.g. `/api/v1/ai/hermes/engine`:

* `GET`: selection, effective engine, target default, live readiness, available engines, published version ID, revision, and error code.
* `PUT`: `{ "active_sales_engine": "langgraph", "change_note": "Keep the existing engine" }` (Staff Superadmin only). Re-selecting the same engine is a no-op. Switching or repairing a previously different persisted engine creates an audited P05 version. Prompts and selected model are not rewritten with other values. A Hermes request returns `409 HERMES_NOT_READY` without a mutation in this release.
* Draft/publish/restore remain separate; the selector is not part of editable prompt policy. `enabled` still retains its original Hermes policy meaning. `GET /ai/hermes/global` also reports `engine_selection` independently of `configuration`.

Expected GET for a pre-HEI registry:

```json
{
  "active_sales_engine": "langgraph",
  "effective_sales_engine": "langgraph",
  "target_default_engine": "hermes",
  "hermes_live_ready": false,
  "available_engines": ["langgraph"],
  "automatic_fallback": false,
  "error_code": null
}
```

Version ID/revision are also returned and reflect actual data. Selection and readiness are not inferred from the old UI.

## 4. Routing boundary and persistence

- Existing webhook queue/FIFO/legacy dispatch handlers are reused. The worker resolves the event with the existing `AgentRun.event_id`, then records a `sales_engine_pin` in the existing `SalesMessage.metadata_json` (inbound) or `SalesFollowUpJob.payload_json` (scheduled). It includes event, company, project, lead, conversation, engine and known policy-version ID. No new column or table. Legacy policy-version selection remains the existing coordinator's responsibility; HEI-01A does not change it.
- A pin or existing run owns the retry; it cannot be reassigned simply because a global selection changed. Conflicting or unavailable ownership goes to review rather than another engine. Already claimed legacy work uses its original handler. The selector does not create a second `AgentRun`, and it does not perform LLM inference.
- Existing simulation uses the same selection contract and returns a conflict before execution/unpause when no supported route exists. Existing completed/blocked simulation runs retain their prior idempotent response behavior.
- Scope, delivery, consent, pause, opt-out, calendar, provider signatures and transactional business checks in the existing handler are not replaced. Deleted leads and explicitly mismatched opportunities are not dispatched by the routed worker. Existing first-contact templates and deterministic notices remain unchanged.
- The live worker is the production queue boundary identified in HEI-00. Direct internal legacy helper invocations are not rewritten here; before Hermes can be enabled, HEI-01B must confirm that all generative entrypoints are routed and wire a real handler, plus controls such as STOP/human takeover in the Hermes path. Legacy deterministic control/notice behavior is preserved while legacy remains active. Do not interpret this patch as certifying those controls with Hermes. No real execution is allowed merely because a future readiness flag is changed.
- Missing P05 tables or DB errors must not be interpreted as a selected engine. Existing migration P05 must already exist in the deployed schema; its presence in the code and previous successful deploy is evidence, not a direct production DB inspection. This release introduces no migration. If deployment/CI reveals missing P05 schema or other regressions, stop and inspect rather than changing databases manually.

## 5. Verification performed

The four replaced original files were reconstructed from the GitHub connector and verified against the exact Git blob SHA before making changes:

| Original path | Blob SHA |
|---|---|
| `backend/app/modules/ai_core/router.py` | `b6ed41942dd73b29b1d3213878dd8827dcbb55b4` |
| `backend/app/modules/hermes_sales_core/staff_config.py` | `93662930dc0986b4e2a5dc65805de0c966861776` |
| `backend/app/modules/sales_agent/current_simulation.py` | `7d95a37faa1bf0a7f3a07cd7e086317be1e0689e` |
| `backend/app/modules/sales_agent/live_worker.py` | `a3504943ad1fffaa4d1377820ca627739eeb92bc` |

Local isolated tests (`python -m pytest -q tests/test_bp_hei01a_engine_selection.py --disable-warnings` in a temporary source subset): **30 passed**. Actual HEI modules, exact P05 ORM model/config and conversation scoping helper; SQLite fixtures for Sales rows, test tool/prompt content, mocked identity checks and handlers. No inference, provider or Calendar call. Future-ready scenarios use test-only readiness doubles, not a production activation option. Existing P05 policies and version restore behavior were checked with those doubles. This is not the full legacy regression suite or real auth validation.

Not run here: complete backend CI, Angular build, production PostgreSQL, SDK container/import and OpenRouter, live channels, calendar or actual deployed admin UI. The full private checkout and production server are not available in this local runtime. Use the repository's existing deployment gates; no server write or production action was taken. The original P09.1 pipeline succeeded at the base SHA; that result is not a test of this candidate.

## 6. Acceptance after upload

1. GitHub Actions on the new commit: build backend candidate, three backend regression shards, sales acceptance/isolated PostgreSQL, coverage verification, frontend build, deployment all green. If any gate fails, do not advance to HEI-01B; collect the failing job/trace.
2. Admin with existing Staff Superadmin session: GET `/api/v1/ai/hermes/engine` returns effective `langgraph`, target `hermes`, readiness false. No new version is created just by GET. Ordinary Company roles cannot change this global setting.
3. No unexpected engine change when viewing/editing/publishing/restoring old or Hermes configurations. Existing steps, segments, prompts, scoring and admin UI remain present.
4. Existing authorized Live Test, chat, provider delivery and follow-up behavior remain the same with legacy; no duplicate output, no P09.1 regression. Perform any real message smoke only with an authorized test lead.
5. Verify no migration scripts/new collections or external provider credentials were changed by the differential.
6. Do not select or force Hermes in production until HEI-01B (runtime), HEI-02 (parity), HEI-03 (real receipts), HEI-05 (UI) and HEI-06 (E2E) are certified.

## 7. Next phase

**HEI-01B — Hermes Runtime Integration:** turn the existing pinned, isolated SDK worker into an executable adapter; establish the safe request/response boundary and staging readiness; keep P04/P08 simulation-only guards, and connect only certified handlers. Reuse the HEI-01A router; do not create another database or modify non-chat modules. Continue with HEI-02/03 for continuity and actual business effects before the final default Hermes switch.
