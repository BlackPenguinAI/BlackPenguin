# Parallel backend regression

## Apply

Apply this differential package on top of the successful first pipeline optimization (workflow observed at b84dda7). Copy `.github/`, `backend/` and `docs/` into the repository preserving paths. No deletion, dependency change, migration, new credential or registry configuration is required. Existing Dockerfiles and Docker ignore files from the first optimization remain in place.

## Workflow

Backend and frontend builds still start independently. The API image is built and exported exactly once. Three backend regression jobs and one sales acceptance/PostgreSQL job download and load the same candidate archive, verifying its checksum and revision label. The regression matrix has fail-fast disabled so a failing group does not cancel the remaining diagnostic reports.

Each regression job has its own disposable runner, SQLite database and test upload directory. PostgreSQL checks retain the existing isolated network/database helper. Only test credentials are used in validation. Deployment waits for all three regression jobs, the coverage gate, acceptance/PostgreSQL and frontend success. The production transfer, activation, rollback, migrations, readiness and worker stability steps are unchanged.

## Partition

`backend/tools/ci/test_durations.json` contains only historical per-module durations from the supplied backend-junit.xml. No lead content or provider credentials are included. `shard_tests.py` discovers current `test_*.py` and `*_test.py` files recursively, sorts by estimated duration, and assigns each complete module to the lightest group. New files are automatically included with a five-second initial weight. Removed files disappear from the plan. The policy uses pytest's standard file patterns; update discovery before introducing custom pytest file patterns or custom collection of non-Python files.

On the supplied 104-module dataset, estimated group durations are 221.015, 221.015 and 221.016 seconds. Historical estimates are not guaranteed elapsed times: runner startup, collection, downloads and new tests add overhead. More concurrent jobs increase simultaneous resource usage; compare total Actions minutes as well as elapsed time.

Each shard produces `backend-junit-N.xml` and `shard-N-manifest.json`, retained for seven days in `validation-shard-N-COMMIT`. Acceptance reports are in `validation-acceptance-COMMIT`. The API artifact is a candidate until all gates succeed, even though it is exported before validation. It cannot reach the production deploy job on a validation failure.

`verify_shards.py` requires all three manifests and successful JUnit reports. It rejects missing/duplicated source modules, missing module results and inconsistent plans. Source modules containing no tests will deliberately fail the gate rather than silently disappearing; rename helper files that match test patterns if this occurs. Source tests retain their individual skips, including the separate PostgreSQL tests exercised by the dedicated helper.

## Checks performed

- Eight standard-library safeguard tests passed: new-file inclusion, deterministic assignment, invalid weights/input, missing shard, failed JUnit, missing new module, wrong module report and repeated module.
- All 2,415 historical JUnit cases (2,408 passed, seven skipped) partitioned exactly once across the 104 modules and passed the new coverage gate.
- YAML structure, all inline Bash syntax and deployment dependency gates checked.
- Production deploy steps and frontend job compared to the previously delivered optimization: unchanged.

Docker is unavailable in the preparation environment. No live GitHub Actions execution, image build or full current application suite was run here. The next Actions execution must pass all groups before deploying. This package does not change sales-agent behavior.
