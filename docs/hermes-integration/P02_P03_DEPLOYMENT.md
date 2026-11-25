# BP-HERMES-P23 — Upload and deployment safety

## GitHub Upload Ready

1. Confirm the base branch contains P01 commit `6a684a2846c08a0788e8b1e00fc6dc75e3c1a6b8` or a newer commit that has not changed the touched files.
2. Extract the ZIP on your computer. Upload its **contents**, preserving repository-relative paths. Do not upload the ZIP itself as a single file to the repository.
3. Prefer creating a new integration branch using the GitHub web interface and uploading there first. No patch, installer or local shell command is required before upload.
4. Review the changes and CI evidence; only then merge to `main`.

## Important: `main` automatically deploys to DigitalOcean

The current `.github/workflows/deploy.yml` deploys on `main` pushes affecting `backend/**`. It detects `backend/app/db/` changes and executes `alembic upgrade head` on the production API container. This ZIP modifies `backend/app/db/base.py`, adds an Alembic revision, and **will trigger an additive production schema migration if uploaded directly to `main` and the workflow succeeds**.

Do not interpret "Upload Ready" as "no production effect": uploading to `main` triggers your existing automation. No changes in P23 activate the Hermes agent in live traffic, but migrations still create two empty tables on PostgreSQL. Keep a normal production database backup and use the preview/integration branch first.

The new Alembic revision follows `20261109_sales_worker_progress` and creates only `hermes_sales_states` and `hermes_sales_state_events` plus company indexes. It has no data backfill and does not modify the old LangGraph dialogue tables.

## Rollback

If deployment fails, revert the application commit using your normal deployment workflow. **Do not automatically run Alembic downgrade**: this revision's downgrade drops the newly created Hermes tables and any event evidence they hold. Leaving empty additive tables is safer while investigating.

## Production cutover is out of scope

P23 does not modify `app.main`, `sales_agent.live_service`, `sales_agent.live_worker`, provider webhooks, Nginx, frontend routing or Google Calendar. The `HermesSalesRuntime` remains protected by the P01 lock and is still not routed to production leads. P4 must introduce isolated workers and operational action receipts before any live send.

## Staff global configuration

Current Hermes P01 settings are pinned in code and environment. Configuration publishing from Staff Superadmin will come in P5. No company/project-specific Hermes prompt override is introduced by this package.
