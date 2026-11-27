# HEI-06A.2a — Closed Persistent Staging Foundation

## Scope and certification boundary

Candidate reference: `a61178b09f1856d42a6698fd3f0eddf8e4ae0ab6` (HEI-06A.1 offline and real SDK passed in [run 45973452686](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45973452686)). Conversation baseline: `92769b08ef8495bba711951594adcef26951752c`, 18/18 real SDK conversations in [run 45963307886](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45963307886). Reference architecture: `jorgektch/testing-hermes-agent`.

This differential is the first implementation of persistent staging (A.2a). It provides an isolated control-plane environment, not a functioning live Hermes sales channel. A.2b must separately implement and certify scoped staging activation at enqueue, preparation and dispatch, including revocation and uncertain effects. The original hard production gate stays false. Do not use the disposable HEI-06A.1 fixture override in this environment. No source under `backend/` or `frontend/` or existing deployment workflow is replaced. No model or external provider credentials are used. No production deployment or VPS provisioning is performed by this package.

The exact API image and existing sales worker (which runs inside the API lifespan) are used. There is one API process and therefore one sales worker. No second sales worker or onboarding worker is started. The SDK runs as a separate private service using the existing, pinned Dockerfile. It responds to its existing authenticated endpoint but correctly denies preparation (503). There is no model inference in this phase. The Angular image is built from the actual frontend with staging-only origin rewriting, not a different UI. Browser execution and complete UI navigation are not yet certified; the acceptance probes HTTP and selected administrative endpoints.

## Topology and restrictions

- Persistent PostgreSQL 16 named volume and unique Compose project derived from a random deployment identity. No production database address, external volume, host database port, or restored customer data.
- API, SDK and PostgreSQL join only a Docker internal network; no host ports. API and SDK run as uid 10001 with dropped capabilities. Frontend joins that network and a separate bridge so the host can reach its only binding `127.0.0.1:18082`. Use a dedicated staging host. No external tunnel is created automatically.
- Existing production Nginx upstream is not used: staging Nginx resolves `api:8000` on Docker DNS. The build-copy rewrite replaces the hard-coded production API origin, including `AuthService`, and directs the superadmin to the Hermes configuration screen. CSP restricts browser fetches and resources to the same origin (with local data/blob images). External fonts and other resources may be blocked intentionally. Do not reuse the production browser session or allow public ingress.
- `guard.py` checks exact PostgreSQL hostname, database/user, major version, purpose, random installation marker, candidate commit, distinct secrets and absent external credentials. `bootstrap` creates ORM tables and synthetic seed data only when the database contains exactly its new marker. DDL and seed are within one transaction. It never calls the destructive `app.init_db` and never drops tables. This is an ORM-created test schema, NOT a migration-chain certification. A populated database bound to a different candidate is rejected; future upgrades need reviewed backup/migration/release procedure.
- The API wrapper is default-deny. It permits local login, selected health endpoints, staff policy read/draft/publish/restore, selector read/change (the native gate rejects Hermes), and selected read-only conversation endpoints. Webhooks, lead creation, sending, booking, provider configuration/OAuth, password recovery and arbitrary writes are denied. The application still applies native JWT and role checks. Other Angular screens may return 403; intentional for this limited control plane. The synthetic lead and project are marked demo, and the conversation and agent are paused. No live job is seeded.
- Policy publication changes the isolated DB only; `enabled=true` does NOT authorize Hermes routing. Real Telnyx, Google Calendar, Firebase, SMTP, OpenRouter and external API access are excluded. The isolated network is an additional containment layer, not a general-purpose security guarantee for arbitrary host administrators.
- Emergency containment: `manage.py stop` stops frontend, API (including worker) and SDK, preserving PostgreSQL. `down` removes project containers/networks without deleting its named volume. This is an infrastructure stop, not a certified per-lead kill switch or a guarantee about in-flight external operations. No external operations are enabled in this release.

## 1. Upload Ready

Upload all files in the ZIP at their repository-relative paths via GitHub Upload files. Ensure `.github/workflows/hermes-hei06a2-persistent-staging.yml` is present. Commit message:

`test(hermes): add isolated persistent staging control plane`

No new GitHub secrets or production environment changes. Existing normal workflows may run according to their trigger rules; the new workflow does not alter or invoke them. The new workflow is manual-only and runs only on a hosted ephemeral GitHub runner. It checks that the candidate differs from the accepted baseline only in this package and checks the exact closed engine gate blob.

## 2. First execute CI, not a server deployment

Actions → **Hermes HEI-06A.2 persistent staging foundation** → Run workflow → main. No `run_openrouter` option. The workflow builds three candidate application images plus PostgreSQL, starts the isolated stack, checks actual network/port topology, exercises the real proxy and API, publishes a policy, verifies scope and blocked actions, confirms the real worker's scan health, recreates the stack while keeping the volume, then verifies the same policy ID and synthetic scope. Hosted-only cleanup deletes its own temporary volume, and checks no resources with that project's Compose label remain. A normal operator does not have a volume deletion action.

Expected artifact: `hei06a2-foundation-<sha>` containing `initial.json`, `recreated.json`, `summary.json`. PASS requires both probes and cleanup. Summary explicitly leaves `real_inference`, `live_staging_authorization`, `real_provider_acceptance` as NOT_RUN, production readiness CLOSED. Reports use a synthetic policy identifier and sanitized checkpoint/type, not passwords, JWTs, database URLs, provider tokens, or raw responses.

If failure occurs, preserve the failing report and job URL, do not retry repeatedly or remove guards. Docker image build, real API startup, Angular compilation, actual PostgreSQL, real policy publication and HTTP tests were not run locally because Docker and a full private repository checkout are unavailable here.

## 3. Optional dedicated staging host (only after CI passes and operator approval)

Provision a separate Linux VM with Docker Engine + Compose v2, Git, Python 3 and adequate storage. Use a fresh checkout of the same approved commit; no production `.env`, customer data, or provider credentials. Do not run this procedure on the production DigitalOcean host. No remote deploy workflow is included. The operator remains responsible for firewall, SSH and host hardening. Do not open TCP 18082 publicly. The manager supports only local default Docker context and a clean checkout; build steps may need Internet, application containers do not.

From the repository root (initial provisioning once):

```bash
python3 services/hermes_worker/persistent_staging/manage.py init "$HOME/.bp-hei06a2"
python3 services/hermes_worker/persistent_staging/manage.py up "$HOME/.bp-hei06a2"
python3 services/hermes_worker/persistent_staging/manage.py probe "$HOME/.bp-hei06a2"
```

The first command generates `staging.env` with random, distinct 256-bit credentials in an external mode-700 directory; file mode 600. Never paste or upload this file, commit it, or use production passwords. `probe` publishes the restricted synthetic policy if none exists; it is not a purely read-only command. It then verifies native Hermes selection remains blocked. No other business operation is authorized.

Use an SSH local tunnel from the operator's machine (replace host/user with actual staging server):

```bash
ssh -N -L 18082:127.0.0.1:18082 <user>@<staging-host>
```

Open `http://127.0.0.1:18082/login` in a dedicated browser profile. Local user: `staging-admin@example.invalid`; password is the `STAGE_ADMIN_PASSWORD` in the private state file. The targeted settings route is `/admin/ai-settings/hermes`. Never send that password to chat or GitHub. The native policy API is `/api/v1/ai/hermes/global`; the scoped inspector endpoint is `/api/v1/ai/hermes/staff/conversations/stg-conversation/context?company_id=stg-company&project_id=stg-project&lead_id=stg-lead` (requires staff bearer). Complete browser interaction is not certified by HTTP probes.

Operations (same exact checkout):

```bash
python3 services/hermes_worker/persistent_staging/manage.py status "$HOME/.bp-hei06a2"
python3 services/hermes_worker/persistent_staging/manage.py stop "$HOME/.bp-hei06a2"
python3 services/hermes_worker/persistent_staging/manage.py down "$HOME/.bp-hei06a2"
python3 services/hermes_worker/persistent_staging/manage.py up "$HOME/.bp-hei06a2"
```

`stop` and `down` preserve the DB volume. Do not use `docker compose down -v`, `docker system prune --volumes`, or production migration/reset commands. Back up the isolated volume and securely retain the identity file before any future upgrade. `up` requires the pinned SHA and does not migrate an existing database. Lost identity/credentials are not recovered automatically. `ci-clean` is restricted to GitHub-hosted CI under RUNNER_TEMP, never the operator host.

## 4. Local validation

14 unittest cases passed: environment and secret format, external key rejection, DB identity, URL, allowed/denied routes, marker/candidate mismatch, fresh bootstrap flag and state file integrity/permissions. Marker tests use doubles; they do not contact PostgreSQL. Python AST, YAML parsing, shell syntax, Nginx syntax (`nginx -t` with a temporary standalone config) and Node syntax passed. A sample AuthService copy was rewritten correctly. The actual Angular build and all cross-container tests remain pending CI. No production code or remote repository changed.

## 5. Remaining roadmap

- A.2a: closed persistent foundation — this package; pending CI and optional separate host provisioning.
- A.2b: real staging-only authorization, not a global env flag or monkeypatch; scoped admission and revalidation at worker/SDK and before effects, emergency revocation, negative tests across company/project/lead, no production gate changes; real synthetic Hermes turn over the persistent stack and full inspector/browser acceptance. Dedicated OpenRouter egress design and budget must be reviewed.
- B: real Telnyx with owned test numbers and explicit consent, callbacks and actual receipts. C: separate Google Calendar/test advisor, book/reschedule/cancel and rollback. Do not activate Hermes in production until those controls and real provider acceptance pass.


## Startup evidence hotfix — base ecaab5d

Run #1 (45977591412) successfully built all three images and initialized PostgreSQL, but the API became unhealthy approximately 2.5 seconds after starting. The original CI cleanup removed the containers before recording their internal startup diagnostics. The underlying exception is not confirmed.

This differential adds structured startup checkpoints to the isolated entrypoint, calls the original application readiness function after schema initialization and before serving, explicitly enables ASGI lifespan, and retains the original HTTP readiness requirement (HTTP 200 and status ready). It does not change the production gate, application modules, provider credentials, data model or commercial logic.

The failure-only workflow step runs before cleanup and records `startup-failure.json`: known service names, container state, exit code, OOM flag, restart count, health status, and allowlisted startup/health events. Exception messages, response bodies, environment variables, SQL and raw Docker logs are not exported. The startup phases distinguish `database_identity`, `register_orm`, `api_import`, `api_schema`, `api_lifespan`, and `health_http`. In case of failure share this artifact or its JSON, not raw environment or credentials. If the API dies before emitting any marker, the Docker state will still indicate whether the process exited or was OOM-killed.

Re-run the existing manually dispatched workflow on main after uploading the complete files in the differential; do not start persistent staging on a server before acceptance. The workflow still requires initial and recreated probes and retains its cleanup step. A passing startup alone is not certification. No new secrets.

Local validation: 20 standard-library unit tests (14 existing plus 6 diagnostics tests), Python compilation and YAML parse; full Docker/HTTP/PostgreSQL run remains pending GitHub Actions. This is a diagnostic hardening, not a verified correction of the unknown original startup exception.
