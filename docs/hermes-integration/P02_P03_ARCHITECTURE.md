# BP-HERMES-P23 — Delivery 2 architecture (P2 + P3)

## Verified source pins

- BlackPenguin `BlackPenguinAI/BlackPenguin`, `main` at `6a684a2846c08a0788e8b1e00fc6dc75e3c1a6b8` (includes P01).
- Hermes demo `jorgektch/testing-hermes-agent`, `main` at `9ac4c8703d28eb3ca39fc762df0dd67c7196e324` (v13.3.3).
- P01 foundation unchanged except `hermes_sales_core/runtime.py`: adds *opt-in* read-only-state-draft capability. Original P01 default denies all eight unsafe tools.

## Ownership boundaries

| Concern | Owner in P23 | Safety |
|---|---|---|
| Company and project authorization | `bp_context.require_scoped_entities` | Validates all four IDs and active opportunity against BP ORM |
| Company onboarding information | `bp_context.build_bp_snapshot` | Uses only valid published Company snapshot + reviewed public fields; logo presence only |
| Project, property types, units, inventory | BP `sales_agent.commercial_context.build_commercial_context` | Published/confirmed source, not in-progress drafts |
| CRM lead facts | BP `sales_agent.lead_profile` and Lead ORM | Scoped to company/project/conversation/lead |
| Hermes tool reads | `bp_read_port.BlackPenguinReadPort` | No SQL mutations or external services |
| Buyer long-term preference updates | Same port, **in-memory draft only** | Derived from the current buyer message; LLM arguments never override explicit values |
| Durable Hermes state | `bp_state_store` + `bp_models` | New independent state/events tables, scoped CAS and event idempotency |
| Actual provider delivery | NOT IMPLEMENTED IN THIS DELIVERY | Existing BlackPenguin services unchanged |
| Calendar booking/rescheduling/canceling | NOT IMPLEMENTED IN THIS DELIVERY | All operational Hermes tools disabled |
| Tool registry concurrency | P01 process lock remains | Isolated production worker deployment deferred to P4 |

## Scope and approved-source contract

`TurnScope(company_id, project_id, conversation_id, lead_id)` is a server-side association, not a permission created by the LLM. `require_scoped_entities` checks `Company`, `Project`, `Lead`, `SalesConversation`, and an active `SalesConversationLeadContext` when that table contains contexts.

`build_bp_snapshot` requires an approved project and uses BlackPenguin's current published commercial-context builder, which already reconciles published project snapshot, confirmed catalog types, inventory and approved asset metadata. It removes link and storage fields before providing content to Hermes. Company onboarding fields are included **only** if a valid published snapshot proves per-field confirmation. Company `tone_of_voice` cannot override the global Staff prompt.

In P23 only the **English global prompt** and P01 `openai/gpt-4o-mini` model defaults exist. Admin-panel editability is P5 and remains global (not per company).

## Business tool contract

P23 implements read-only tooling via the same Hermes ToolPort interface:

1. `get_project_overview`
2. `search_properties`
3. `evaluate_properties_for_lead`
4. `get_unit_details`
5. `compare_properties`
6. `list_unit_assets` (metadata discovery only, no links)

`update_search_preferences` may be **opted in by trusted Python code** to update the *working in-memory draft*, using values extracted from the current buyer utterance. It cannot persist or update the BP CRM on its own. No browser/API exposes the opt-in.

All other state mutations and real effects remain denied, including `get_unit_media`, `get_available_visit_slots`, `select_visit_time`, `book_onsite_visit`, `cancel_onsite_visit`, `reschedule_onsite_visit`, `track_property_interest`, and `update_lead_profile`.

### Inventory and price safety

- A `ProjectPropertyType` is **not** a physical `ProjectUnit`; the adapter returns an explicit `kind`.
- Unit selection resolves only within the scoped project. The same visible unit code may exist in different projects.
- USD amount filters compare **only USD catalog prices**, never PEN or a currency with unknown conversion. Noncomparable entries go to `unverified_references`.
- Missing amounts, features, inventory verification dates, and requested facts never become false matches.
- Sold/reserved/unavailable units are excluded from search results; undated/uncertain units are reported as unverified.
- No calendar availability is claimed from catalog status. Available slots are a P4 capability.
- A target/preference is not silently promoted to an absolute budget cap. Persisted hard caps and exact bedroom requirements survive new searches.
- This P23 adapter intentionally prioritizes **honest conservative coverage** over returning optimistic matches. Rich relative/currency search and verified closest alternatives require further P4 test cases.

## Hermes state persistence

New tables, separate from `sales_dialogue_states`/`sales_dialogue_events`:

- `hermes_sales_states`: unique `(conversation_id, lead_id)`, scoped IDs, schema/version, revision, JSON state, updated date.
- `hermes_sales_state_events`: unique `(conversation_id, lead_id, event_key)` and `(conversation_id, lead_id, revision)`; JSON snapshot per event; ORM append-only guard.

The state store:

- Returns a clean blank state for uninitialized conversations; no LangGraph conversation-state conversion.
- Validates scope and project/property references on every load/write.
- Rejects illegal state keys, known credential field names, non-JSON/nonfinite values and payloads over 256 KB.
- Uses Postgres `SELECT FOR UPDATE` + SQL `revision = expected_revision` compare-and-swap, with unique event keys for idempotency.
- Does **not** call `db.commit()`; caller controls the outer transaction and rollback.
- Allows a buyer-visible menu to be stored only after validating an existing accepted/sent outbound message and exact numbered visible options; hidden tool results alone confer no choice authority.

The optional `commit_simulation_receipt` further requires an existing persisted in-app `SalesMessage` of channel `simulation`, status `sent`, exact reply content, and explicit `engine='hermes-agent'` plus `hermes_inbound_message_id` metadata. No endpoint currently creates this receipt automatically: it is a contract for the next integration stage.

## Source layout

```text
backend/app/modules/hermes_sales_core/
    bp_context.py         # Scoped BP approved sources
    bp_read_port.py       # P02 safe read-only tool implementations
    bp_models.py          # P03 additive SQLAlchemy tables
    bp_state_store.py     # P03 transactional state / CAS ledger
    bp_turn.py            # Simulator-only, no-dispatch prepare + receipt helpers
    runtime.py            # P01 runtime + opt-in in-memory preference-draft permission
backend/app/db/base.py    # Register new ORM models for metadata/migrations
backend/alembic/versions/20261125_hermes_sales_p03.py
backend/tests/test_bp_hermes_p02_catalog.py
backend/tests/test_bp_hermes_p03_state.py
```

## Deliberately not included

- Production route/workers, Telnyx/Twilio calls, real calendars, booking, cancellation, share-token issuance, CRM writes, migration of historic LangGraph conversations, LangGraph removal, or Angular admin changes.
- Real SDK, OpenRouter, DigitalOcean and Postgres multi-worker tests: these require a staged environment and P4/P7 activation.
- Automatic generation of menus from arbitrary Hermes text: future release will use typed, confirmed tool results with exact delivery receipt.

P23 is safe to merge after reviewing additive migration, but is **not** a feature launch. Actual substitution follows P4-P8.
