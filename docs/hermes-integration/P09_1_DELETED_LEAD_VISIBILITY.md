# P09.1 — Deleted Lead Visibility & Access Hotfix

## Base and packaging

- Based on `BlackPenguinAI/BlackPenguin` main commit `80d7ee7cfed70ad5bcb8acc18df1e76579306fe0` (P09 guarded stage).
- ZIP contains **complete files with repository-relative paths**; extract and upload directly through GitHub's web "Upload files" flow.
- No patch, installer, migrations, environment variables or commands need to run **before upload**.
- This is an additive, non-destructive hotfix; it does **not** activate the guarded P09 hard-delete lane.

## Root cause

`/app/leads` hides leads marked with `deleted_at`, but `/sales-agent/conversations` previously returned every physical conversation linked to the Company, including soft-deleted leads. The Angular polling code then kept a vanished `selected` conversation open with old messages and an unusable context panel.

## Changes

1. `p091_visibility.py` adds a **first-match GET /sales-agent/conversations** route which preserves existing authorization, project filtering and redaction but returns only leads whose `deleted_at IS NULL` in the authenticated Company. It sets `Cache-Control: no-store`.
2. The existing Agent router receives a **guard dependency** for every route containing a `conversation_id`; direct reads of messages, operational context, Hermes state and mutations (including resume, retry, manual send) return `404` when the lead is deleted or missing.
3. The Agent UI route uses an additive `AgentP091Component`, inheriting the original Angular template and behavior; it clears `selected`, messages, slots and review state whenever the server's refreshed inbox no longer contains the selected conversation.
4. The old CRM deletion semantics remain unchanged, as do the P09 guarded hard-delete preview and disabled hard-delete endpoints.

## Acceptance checklist

- [ ] Delete a Company C1 lead from `/app/leads`; its conversation vanishes from `/app/agent` after the next poll (normally 2 seconds), including the open detail/context panel, without refreshing the browser.
- [ ] `GET /api/v1/sales-agent/conversations` does not return that lead.
- [ ] `GET /api/v1/sales-agent/conversations/{old-id}/messages` returns 404.
- [ ] `POST /api/v1/sales-agent/conversations/{old-id}/manual-message` and `/action` return 404.
- [ ] Other active opportunities in Company C1 remain visible, including leads on different projects and the same phone number.
- [ ] Company C2 conversations remain unaffected; the authenticated Company/project checks still apply.
- [ ] No messages are sent to the deleted lead after the deletion.
- [ ] The existing P09 tests and whole CI deployment still pass.

## Known boundaries

- This hotfix **hides and rejects access**; soft deletion still retains historical conversations, messages, appointment records and Hermes/LangGraph state in PostgreSQL. The separate P09 hard-delete migration remains unfinished.
- A physical provider thread reused between opportunities still requires the planned P09 multi-opportunity normalization before independent physical deletion is safe.
- A message already accepted by the external provider before a deletion cannot be recalled. Full provider concurrency certification is part of the subsequent P09 work.
- The Agent visibility override delegates to the established `conversation_summaries` path, then filters the result for deleted leads; a later code cleanup can move this predicate into the original SQL query after the legacy thread migration.

## Local validation

`pytest -q backend/tests/test_bp_p091_deleted_lead_visibility.py` — 4 passed with SQLite fixtures.

Python `compileall` and TypeScript syntax parsing — passed. Full backend integration tests, frontend Angular build, real PostgreSQL and provider E2E were not run in this environment.
