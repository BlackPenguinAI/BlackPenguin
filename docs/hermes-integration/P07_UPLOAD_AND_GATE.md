# P07 Upload Ready — GitHub and operational verification

## Upload

1. Extract `blackpenguin_hermes_p07_upload_ready.zip` locally.
2. Upload the **files inside** the archive to `BlackPenguinAI/BlackPenguin` in the same repository-relative paths (`backend/...`, `docs/...`). This is a full-file differential, not a patch or an installation script.
3. Prefer a new integration branch / PR before merging. Publishing to `main` automatically triggers `Deploy Black Penguin API, Worker & Frontend to DigitalOcean`.
4. No terminal work, script, migration, or dependency setup is required **before uploading**.

## Expected CI behavior

- Python backend shards run the added P07 offline tests. The three PostgreSQL-only tests are skipped in SQLite shards, explicitly documented as **NOT RUN** there.
- The predeployment `sales-acceptance` stage runs the isolated PostgreSQL script with the same candidate API Docker image and must report **14 total, 0 failed, 0 skipped, PASS**.
- Existing Angular build, shard completion, 64-case Sales acceptance and DigitalOcean stages retain their existing workflow rules. P07 does **not** change the production engine selector.

If PostgreSQL 14/14 does not pass, **do not deploy or proceed to P08**. Inspect the uploaded `validation-acceptance-<sha>` artifact's `postgres.log` and `postgres.json`. The logger intentionally avoids printing passwords.

## Optional acceptance checks after CI

- As Staff Superadmin, confirm global Hermes settings still load and that publishing a draft has no impact on live agent routing.
- Confirm `GET /api/v1/ai/hermes/global` is forbidden without Staff permission; tenant role paths remain read-only and company-scoped.
- In a staging-only isolated Hermes SDK process, load a published configuration with a restricted tool set, verify that the SDK reports only that tool and that disabled ones hard-fail. Do **not** run the SDK against production leads or real channels for P07.
- In Staff Monitor and Agent, verify Hermes context is absent when no Hermes state exists; never invent or backfill historical LangGraph state.

## Safety and rollback

P07 modifies only isolated Hermes runtime preparation, Python tests and the predeployment isolated PostgreSQL test harness. **No Alembic migration, production DB reset, real booking execution, calendar access, WhatsApp/SMS sending, or LangGraph routing replacement.** A normal Git revert/rollback of this differential restores the previous behavior. Do not enable Hermes production dispatch until P08 gates have passed.

## Suggested commit

`test(hermes): enforce published tool policy and add PostgreSQL P07 gates`
