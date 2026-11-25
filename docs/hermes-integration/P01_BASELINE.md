# BP-HERMES-P01 — Baseline (2026-11-25)

## Repositories and immutable source commits

| Source | Branch | Commit | Intended use |
|---|---|---|---|
| `BlackPenguinAI/BlackPenguin` | `main` | `0ab19e793540737626c259d8a20883330fa65143` | Destination: FastAPI + PostgreSQL + Angular 21 |
| `jorgektch/testing-hermes-agent` | `main` | `9ac4c8703d28eb3ca39fc762df0dd67c7196e324` | Validated Hermes demo v13.3.3 |
| `NousResearch/hermes-agent` | pinned dependency | `b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb` | Upstream real `AIAgent` SDK used by the demo |

A later commit to either repository must **not** silently replace these baselines.
The incremental zip contains **new files only**. There is no replacement of a
live BlackPenguin route, service, model, migration, Dockerfile, or frontend file.

## Source provenance

- `hermes_runtime.py` in the source demo supplies `AIAgent` invocation semantics,
  the `registry.register` interface, OpenRouter defaults, 12 iteration limit,
  toolset allowlisting, `run_conversation`, and use of `persist_user_message`.
- `contextual_choices.py` (v13.3.3) is copied intact; it implements typed,
  buyer-visible contextual menus and ordinal selection.
- `property_options.py` (v13.3.2 base of the v13.3.3 demo) is copied intact.
- `conversation_context.py`, `commercial_turn.py`, `sales_preferences.py`, and
  `property_filters.py` have been ported into the new independent package,
  retaining the narrow conservative semantics and original demo-specific
  H-### / USD conventions where applicable.
- `runtime.py` is newly written to isolate the AIAgent bridge from the demo
  database and Flask/FastAPI endpoints. It delegates tool implementation to an
  injected `ToolPort`, with no SQL/provider code.
- `tool_schemas.py` ports the **15 demo tool names and argument shapes**. It is
  not a verbatim copy of every tool description: descriptions have been edited
  to clarify that the backend business gateway will authorize effects.
- `prompts/global_en_v1.txt` preserves the demo's key interaction policy but
  deliberately removes its *fictional-project* introduction and synthetic
  disclosures. This is a candidate English-only global prompt, **not yet
  published or loaded from Staff Superadmin**.

## Existing BlackPenguin contracts relevant to next phase

- Angular frontend: `frontend/src/app/pages/client/agent`, `leads`, `sales`,
  `features/admin-panel/ai-settings`.
- FastAPI: `backend/app/main.py`, `/api/v1/sales-agent/*` and `/api/v1/ai/*`.
- Existing PostgreSQL identities: `leads`, `sales_conversations`, `sales_messages`,
  `agent_runs`, `sales_dialogue_states`, `sales_dialogue_events`, `meetings`,
  `project_property_types`, `project_units`, `project_sales_assets`.
- Live webhook/queue and dispatch: `provider_router.py`, `live_worker.py`,
  `live_service.py`, `sales_inbound_jobs`, `outbound_messages`.
- **No** historical LangGraph test conversations need to be migrated.
- **No** per-company or per-project prompts/settings for Hermes.
- **English only** and global Staff Superadmin policy for this milestone.

## Known critical boundaries

1. `run_agent.AIAgent` and its tool registry must be isolated across worker
   processes. A lock protects registration within **one** process only.
2. All 8 effect-capable/demo-state-mutating tools are intentionally denied in
   P01. No simulation of a committed real-world transaction is implied.
3. The current demo's `domain.py`, `scheduling.py`, `delivery_policy.py`,
   and v13.3.3 *monkey-patch adapter* remain coupled to demo data and turn flow;
   they have NOT been moved as production code. P02–P04 must reproduce their
   validated outcomes using BP data and receipts, not by injecting fake JSON.
4. Existing BlackPenguin LangGraph code is **not removed in this package**;
   it is also **not used or imported** by this independent Hermes package.
5. No actual OpenRouter invocation or Nous Research SDK installation was
   possible in this offline test environment. That must be verified in the
   isolated Python 3.12 Hermes worker before enabling integration.

## Acceptance for P01

- [x] Independent package imports without Hermes SDK or BP DB dependencies.
- [x] SDK public invocation/allowlist contracted by an isolated fake-SDK test.
- [x] Fifteen tool signatures and an explicit P01 effect-deny list.
- [x] Contextual choice, focus, preference and filter pure regressions.
- [x] Incremental zip only includes new repository-relative paths.
- [ ] Integration with actual pinned Hermes Agent SDK in an isolated container.
- [ ] End-to-end parity with the current synthetic demo `domain.py`.
- [ ] PostgreSQL company/project/lead tool adapters.
- [ ] Production-safe multiworker deployment, bookings, provider dispatch.

The unchecked items are **future work**, not P01 accomplishments.
