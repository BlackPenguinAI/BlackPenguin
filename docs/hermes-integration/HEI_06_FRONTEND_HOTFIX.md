# HEI-06 — Zoneless inspector test hotfix

Base: `a167210cc868620075dfa2299b43ed0880719924` (main).
Evidence: workflow run `45887503400`, attempt 3; artifact hashes verified.

- `sdk-and-postgres`: success. Pinned Nous SDK build/import; offline harness 1/1; disposable PostgreSQL worker 14/14, zero failures/skips. Model and provider calls simulated.
- `frontend`: 12/14. Both HEI-04 DOM-render tests failed with NG0100; the other two HEI-04 tests and all ten HEI-05 tests passed. The workflow stopped before its Angular compilation step.
- `openrouter-real-sdk`: skipped, not a credential rejection. The job requires a new workflow_dispatch with `run_openrouter=true`; rerunning a previous dispatch keeps its original inputs.

## Fix

The previous DOM tests mutate `tab` or call `showEvidence()` directly after initial rendering. Angular 21 zoneless detects stale bindings because these mutations bypass the template event notification. Replace those interactions with real DOM button clicks and await `fixture.whenStable()`, including the initial render scheduled by `componentRef.setInput`. Retain existing assertions and the four test cases; verify selected-tab accessibility state and refresh/reassignment behavior in the second render test. The other two direct logic tests do not mount an Angular view and remain unchanged.

Reference: https://angular.dev/guide/zoneless and https://angular.dev/guide/testing/components-scenarios .

No production component, workflow, test count, database schema, readiness gate or provider behavior changed. No change-detection checks are disabled. The base file Git blob was checked against GitHub before modification. Local TypeScript syntax verification only; npm registry DNS unavailable, so Angular/Vitest execution must be verified in Actions. Diagnosis is based on the failing JUnit, source code and Angular's documented zoneless behavior; exact reproduction and confirmation require the new CI run.

## Upload and re-evaluation

Upload the complete files at their repository-relative paths. Commit: `test(hermes): exercise inspector through zoneless DOM events`.

After upload, push-triggered HEI-06 runs offline lanes; expect 14/14 frontend tests and a successful build. Start a **new** manual `Hermes HEI-06 isolated evaluation` run on main with `run_openrouter` checked to execute paid inference using the already-configured `HEI06_OPENROUTER_API_KEY`. Do not use Re-run jobs on the old run, which retains the old commit and inputs. Do not disclose the secret. Inspect the four job results and reports from the same new commit. Real Telnyx and Calendar remain uncertified. The live readiness gate remains closed.
