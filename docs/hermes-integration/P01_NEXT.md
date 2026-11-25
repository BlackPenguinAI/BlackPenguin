# P02 + P03 entry checklist

1. Obtain a deployable Python 3.12 image with the exact pinned Hermes Agent
   commit, validate the public API surface using a self-contained offline turn.
2. Define typed adapter contracts for `Project`, `ProjectPropertyType`,
   `ProjectUnit`, confirmed inventory, project assets and lead facts in BP.
3. Remove H-### / USD / Lima assumptions from pure helpers only after
   preserving the Hermes v13.3.3 regression corpus.
4. Replace demo `domain.py` tools with BP scoped and read-only gateway tools,
   preserving Hermes' turn ordering, search vs primary preference semantics,
   referent choice and confirmation discipline.
5. Design Alembic migrations for `hermes_conversation_states` with revision,
   schema version, immutable outbound option sets and state change receipts.
6. Deploy isolated single-turn Hermes worker processes with safe limits and
   leases; never let two workers execute the same conversation concurrently.
7. Add typed configuration resolution for one global Staff published policy
   after the runtime is connected, without per-company overrides.
8. Keep real SMS, WhatsApp, calendars, material link issuing, and mutable CRM
   actions disabled until the transaction-safe P04 tool gateway is accepted.
9. Route *new* test conversations to Hermes only when the whole integration
   is ready; no need to backfill old LangGraph test conversations.
10. On any serious Hermes error, stop/retry safely or ask for human review;
    do not fallback into the prior LangGraph commercial engine.
