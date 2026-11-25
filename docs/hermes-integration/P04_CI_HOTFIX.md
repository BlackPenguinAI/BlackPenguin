# BP-HERMES-P04 CI Hotfix — SQLAlchemy fixture cache isolation

## Symptom

The GitHub Actions shard reported `1 failed, 1651 passed, 5 skipped`:
`tests/test_bp_hermes_p04_executor.py::test_operation_model_is_registered_on_same_metadata`.

## Root cause

The P03 `orm` test fixture swaps `app.db.postgres.Base` with a temporary SQLAlchemy `declarative_base()`, but the new P04 operation model and executor may already have been imported by other tests via `app.db.base`. Python caches those modules in `sys.modules`, so `HermesSalesOperation` can remain attached to the earlier, unrelated `MetaData` object even though P03 has created a fresh temporary Base.

## Change

Update **only** `backend/tests/test_bp_hermes_p03_state.py`: evict `bp_operation_models` and `bp_effect_executor` along with the preexisting `bp_models` and `bp_state_store` before swapping the test Base, and restore all preloaded modules after the fixture ends with pytest's `MonkeyPatch.undo()`.

The production Hermes model, SQLAlchemy Base and Alembic migrations are **unchanged**. The metadata identity assertion remains intact; no weakening, skip or xfail is used.

## Local verification

- P03 + P04 executor: **45 passed**.
- Reproduced the failure case by preloading P04 modules on a different Base, then reran the P03 + P04 executor tests: **45 passed** and preloaded module restored after teardown.
- Full locally available Hermes P01/P02/P03/P04 test selection: **155 passed**.

The complete BlackPenguin GitHub Actions suite of 1,657 cases was **not** rerun locally; CI should be rerun after this commit.

## Deployment

This is an **Upload Ready** differential; upload paths relative to the repository root. No pre-upload commands or migrations are required for this fix. GitHub Actions may still trigger on a push to `main`; prefer a temporary branch to verify the shard first.

**Suggested commit:** `test(hermes): isolate P04 model imports in P03 ORM fixture`
