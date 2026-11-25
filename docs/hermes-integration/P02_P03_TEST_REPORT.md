# BP-HERMES-P23 — Local verification report

Date: 2026-11-25. Source repository basis: BP `6a684a2846c08a0788e8b1e00fc6dc75e3c1a6b8`.

## Automated regressions

Run from a checkout of BlackPenguin with the ZIP contents merged:

```bash
cd backend
python -m pytest tests/test_bp_hermes_p01.py tests/test_bp_hermes_p01_policies.py tests/test_bp_hermes_p02_catalog.py tests/test_bp_hermes_p03_state.py -q
```

Test groups:
- P01 runtime and safety policy: 30 tests.
- P02 read tools, approved facts, USD/other-currency handling, draft evidence and fake SDK tool allowlist: 33 tests.
- P03 scoped SQLAlchemy state, event uniqueness, rollback, Alembic upgrade schema match, menu receipts, offline simulation preparation and approved onboarding projection: 33 tests.

**96 local tests passed** using Python 3.13, pytest, real SQLAlchemy/SQLite and a mocked Hermes SDK API surface. The tests do not contact OpenRouter or production database/provider services.

## Important verification boundaries

- The full BlackPenguin backend test suite was **not run** in this isolated environment (only the differential workspace and stand-in ORM models were available).
- The tests verify the actual new migration `upgrade()` through an Alembic SQLite migration context, but do **not** verify PostgreSQL production migration execution or concurrent live DB connections.
- The mocked AIAgent checks the constructor/tool handler interface; it does not establish model-answer quality or production throughput.
- The offline prepare/receipt API is not yet called by the existing live worker. Integration and real-provider tests belong to P4 and P7.
- The P01 process-global SDK lock remains; horizontally scalable isolated-worker deployment is deferred to P4.
- The general BP frontend/CI may run additional tests and must pass before merging to main.

## Security invariants tested

- Wrong Company/Project/Lead/Conversation and inactive lead contexts are rejected.
- An unapproved PropertyType or foreign ProjectUnit cannot be selected as focus.
- Undated inventory and non-USD prices cannot be returned as confirmed USD matches.
- No real Hermes booking, messaging, calendar or asset link tool can execute in P23.
- Only delivered/sent and explicitly numbered output can authorize a durable selected-choice menu.
- Stale revisions, changed duplicate event keys, nested credentials and rollback failures are rejected.
- A simulation receipt requires exactly the output of the given Hermes inbound message.
