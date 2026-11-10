# CI validation and immutable image promotion

## Apply

Copy `.github/`, `backend/`, `frontend/`, and `docs/` from this differential package into the existing repository, preserving their paths. No files must be deleted. Requirements and package.json are unchanged. Existing DO_HOST, DO_USER, DO_SSH_KEY and production application secrets are reused; no registry account or additional secret is needed.

This change is based on the deploy.yml and Dockerfiles supplied on November 10, 2026. Do not overwrite newer workflow edits without reviewing the diff.

## Result

- GitHub Actions builds backend and frontend in parallel on Linux amd64 runners.
- Separate BuildKit GitHub caches retain dependency layers for each image. APP_COMMIT_SHA is declared after dependency installation (and after Angular compilation), so changing the revision does not invalidate those expensive layers by itself.
- The backend image runs the existing complete regression suite, scripted acceptance, and isolated real-PostgreSQL checks before deployment. Tests use dummy credentials, not production secrets. The suite reports the 30 slowest tests and JUnit output. Warning summaries are suppressed; warnings are not converted into passes or ignored failures.
- Validation reports are retained for seven days, including on validation failure. Test runtime and acceptance/PostgreSQL runtime are printed separately.
- Successful images are exported as gzip archives, retained for one day and transferred over SSH. The deploy job depends on both build jobs succeeding. It loads those same images, verifies checksums and revision labels, and never rebuilds or repeats the suite on production.
- Production migration decisions, rollback, upload write check, API/Sales readiness, worker health and stability checks are preserved.
- Docker ignore rules exclude local credentials, dependencies, caches and generated files from build contexts. They do not remove files from the repository.

## Expected workflow

1. Build and validate backend (full tests remain required).
2. Build frontend (in parallel with backend).
3. Deploy only after both succeed: download, transfer, verify, load, activate, health checks.

The first execution has cold caches. Full tests still take time; this package does not promise a specific total duration. Archive transfer adds bandwidth/time. Compare job times and slowest tests after the first two executions. Check Actions artifact storage/minutes usage. The target is linux/amd64; a future ARM migration requires changing both build platforms together.

The production working tree remains detached at the requested commit, as before. Deployments remain serialized. Only repository docs/backend/frontend/workflow changes trigger push deployment. No workflow is added for pull requests in this package.

## Verification performed for this package

- YAML structure and required build/deploy dependency gates checked.
- Every inline shell block parsed with bash -n.
- Activation, incremental migrations and rollback-related remote release sequence compared against supplied workflow; no functional change to that sequence.
- Server has no docker build or pytest invocation; image checksum/revision checks precede activation.
- Dependency layer ordering reviewed in both Dockerfiles.
- Deployment workflow compatibility assertions from the existing sales delivery regression checked against the new workflow.

Docker is unavailable in the preparation environment. No image build, full backend suite, GitHub Actions run or production deployment was executed here. The first Actions execution must validate runner compatibility and the full suite; any failure blocks deployment, leaving running production containers untouched by the new activation step. This package does not evaluate live sales-model quality or fix conversational issues.
