# BP-HERMES-P23 — Delivery 2 (P2 + P3)

**Use this ZIP by extracting it and uploading the extracted contents**, preserving the repository-relative paths. The archive is a differential: only NEW or MODIFIED files appear. No `git apply`, installer, shell script or local command is required before uploading.

Target repository: https://github.com/BlackPenguinAI/BlackPenguin

Base commit (P01 installed): `6a684a2846c08a0788e8b1e00fc6dc75e3c1a6b8`
Hermes v13.3.3 reference: `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`

## Upload steps

1. Extract this archive on your computer.
2. Prefer an **integration branch** in GitHub. Upload all extracted files, keeping `backend/...` and `docs/...` directory paths intact.
3. Review the commit and CI results before merging to `main`.

**Important:** Your current GitHub Actions `deploy.yml` automatically deploys any push to `main` affecting `backend/**`. This package modifies `backend/app/db/base.py`; the workflow detects DB changes and applies `alembic upgrade head` on DigitalOcean. The migration creates **two empty additive Hermes tables** and does not activate Hermes or delete old data. Do not push directly to main unless you intend that deployment/migration.

## Contents

- Approved scoped BP Company, Project, CRM and catalog context adapter.
- Read-only Hermes tool gateway and conservative buyer preference drafts.
- Independent Hermes state + append-only events in PostgreSQL using SQLAlchemy and Alembic.
- Simulation-only Hermes turn preparation and exact persisted-output receipt helper.
- Regression tests and documentation.

## Not activated

NO live SMS/WhatsApp, NO automatic booking, NO asset link issuance, NO CRM writes, NO LangGraph removal, NO new frontend routes. P4 enables operational tools only after real-DB and worker testing.

See `docs/hermes-integration/P02_P03_ARCHITECTURE.md`, `P02_P03_DEPLOYMENT.md`, and `P02_P03_TEST_REPORT.md`.

Suggested commit message:

`feat(hermes): integrate approved BP data and scoped state persistence`
