# Acceptance matrix preflight fix — 2026-11-06

Base commit: `a461e769374111e8b12d946ae22d1d40c9be0c02`.

## Cause and correction

The deployment image contains `/app/app`, and its tests are mounted at
`/app/tests`. The acceptance test previously derived the repository root from
its own location, resulting in `/`, and tried to read
`/docs/sales-agent-acceptance-matrix.json`. That document is not in the image.

The workflow now also mounts `docs` and `backend/tests` under `/preflight`,
read-only, and sets `SALES_ACCEPTANCE_ROOT=/preflight` for that ephemeral test
container only. Existing test execution stays at `/app/tests`, with
`PYTHONPATH=/app` so application imports continue using the backend image.
The second tests mount supplies the relative regression-file references in
the matrix; it does not cause a second suite execution.

The acceptance test uses the explicit root when configured, otherwise keeps
its local repository-root behavior. An invalid override or missing document
fails with an actionable assertion; it does not fall back or skip checks.
The original assertions for all 27 entries and their regression paths remain.
No application code, migrations, credentials or Sales activation settings are
changed. Preflight still runs before replacing production containers; release
and rollback guards remain intact.

## Validation

| Check | Result |
| --- | --- |
| Full suite in repository layout | 1385 passed, 2 skipped; 105.48 seconds |
| Full suite in isolated flattened image/reference layout | 1385 passed, 2 skipped; 105.79 seconds |
| Focused acceptance/layout checks | 6 passed |
| Workflow YAML parse and deployment-script Bash syntax | Passed |
| Read-only mount, image import path, preflight/release ordering checks | Passed |
| `git diff --check` | Passed |

New cases reproduce the original missing-matrix layout, verify the explicit
reference root, reject missing documents and regression files, and reject a
relative override. Two PostgreSQL concurrency tests remain skipped because no
disposable PostgreSQL URL is configured. Existing dependency deprecations
remain in the suite summaries.

Docker is unavailable on the validation host. The isolated run copies the
image-side app/tests/alembic/migrations structure and a separate reference tree;
it is not an actual Docker-image execution or a production E2E test. GitHub
Actions must still confirm the real image preflight and deployment.

## Apply

Copy `.github/`, `backend/` and `docs/` from the ZIP into repository root;
do not omit the `.github` folder. `delivery/` is diagnostic evidence only.
Commit/push and inspect the resulting Actions run. Do not bypass pytest.
After a successful deployment, verify API/worker commit and presence of the
active engine before enabling it for your selected Company/Project. This
patch does not itself enable Active mode.
