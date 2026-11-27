# HEI-06 — Scoped project overview during numbered catalog reconciliation

Base: `fd93f6b507c615849606149b5759b719a1039bd5`.
Evidence: HEI-06 run #8 (45927559039), supplied diagnostic output. Both focus/PDF repetitions passed. Numbered choice repeat 1 passed all checkpoints, including second choice. Repeat 2 stopped at `numbered_search_turn`: `search_properties` and `get_project_overview` executed; reply contained two numbered lines, both property names, and a question; preparation raised `ProductionToolError` classified as `monetary_guard`.

The original monetary rejection's exact text/amount is not captured. The prior repair explicitly rejects every observation except successful `search_properties`, so the extra successful `get_project_overview` independently disqualifies that repair. This overview tool returns scoped approved project facts and catalog coverage without updating the search rows, focus or draft state.

## Changes
- `numbered_catalog.py`: permit successful `get_project_overview` alongside at least one successful `search_properties`. Reject other tools, rejected observations, non-null error codes and malformed observations. Retain the original scope, current inbound search provenance, visible menu, membership/order, filters, single-part bound, and exact monetary/language revalidation in `live_preparation.py` (unchanged).
- Extend the existing unit suite with ten cases (three valid call orders and seven negative combinations). Preserve all prior tests.
- Extend the existing offline harness to invoke the actual overview tool after a search, before returning the synthetic rejected-price reply. Assert both tool observations and retain the full prior assertions, including second-choice focus, PDF replay and STOP. Offline lane remains one test; real lane remains four tests, unchanged.

## Local evidence
Local Python environment from previously extracted API image, SQLite and simulated SDK/providers: 32 numbered catalog unit tests + 1 offline E2E harness; 203 prior HEI tests in one group + 115 in another. Total 351 passed. No real model inference, fresh PostgreSQL or provider calls were performed locally. The three original modified files were verified against the base Git blob SHA before editing. No changes to deployment workflow, global readiness, monetary validator, policy, provider integrations or schema.

## Upload and re-evaluate
Upload the full files preserving repository-relative paths. Commit `fix(hermes): allow scoped project overview during catalog price reconciliation`. Verify the normal deploy and automatic HEI-06 run; launch a NEW manual run of `Hermes HEI-06 isolated evaluation` on main with `run_openrouter` enabled. Do not rerun #8 (old SHA). The already configured secret remains unchanged. Require all four real scenarios to pass and inspect diagnostics. No automatic activation; external provider and private deployment acceptance are still outstanding.
