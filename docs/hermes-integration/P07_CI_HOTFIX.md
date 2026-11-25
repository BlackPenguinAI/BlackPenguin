# P07 CI hotfix — PostgreSQL gate mock count

## Context

Base commit inspected on `BlackPenguinAI/BlackPenguin/main`:
`06ded4fdfe097ac29f53e7d1502e29211dfef332` (2026-11-25).

The P07 extension of `backend/tools/sales_ai/postgres_checks.py` requires
`EXPECTED_CASES = 14`: 11 pre-existing Sales PostgreSQL cases plus three
Hermes P07 PostgreSQL acceptance cases. The existing regression in
`backend/tests/test_sales_delivery5.py` still emitted an 11-case synthetic
JUnit report and asserted that the runner would accept 11 cases. The P07
gate correctly rejected that outdated fixture.

## Exact repair

Update only `test_postgres_runner_refuses_unrelated_image_revision_before_starting_any_database`:

1. Import `EXPECTED_CASES` and `TESTS` alongside `run`.
2. Assert `EXPECTED_CASES == 14` and the Hermes PostgreSQL test module remains
   present in `TESTS`.
3. Generate `EXPECTED_CASES` synthetic JUnit testcase elements and compare
   the returned total against `EXPECTED_CASES`.

All other tests in `test_sales_delivery5.py` are unchanged. No production
files, deployment scripts, database migrations, or safety checks are modified.

## Verification completed locally

- Python syntax compilation: **PASS**.
- Execute the exact updated test function against the P07 runner extracted
  from the P07 Upload Ready archive, with subprocess operations mocked:
  **PASS**; 14 synthetic results accepted; mismatched image revision rejected.
- Additional negative simulation: **PASS**; 11 synthetic results are still
  rejected (`status=FAIL`).
- GitHub Actions full 188-module preflight, real isolated PostgreSQL, and
  container build: **NOT RUN locally**. CI must provide those results.

## Apply

Unzip the differential and upload complete files retaining the original
`backend/tests/` and `docs/hermes-integration/` paths. No pre-upload commands
are needed. Prefer a feature branch because `main` can initiate production
build/deploy workflows.

Suggested commit message:

`test(hermes): align PostgreSQL preflight mock with P07 gate`

Do not upload the P08 staged integration package until the P07 gate is green;
P08 must then be validated on its own commit.
