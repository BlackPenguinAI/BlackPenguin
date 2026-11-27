# HEI-06 — Focused fact grounding evaluation

Base: `0045cd510ed43242511edd766e5255b11d8940b1` (run #10, 45929993567).

## Evidence and scope

The supplied sanitized report records 3/4 real SDK scenarios passing. Both numbered-choice scenarios completed, including the subsequent selection. `focus_pdf/repeat-2` stopped at `named_details_tool`: SDK and worker returned, both reply shapes contained Van Buren and 3 bedrooms, but no explicit `get_unit_details` tool observation was recorded. The PDF follow-up and STOP were not reached for that repetition. This report alone does not prove which evidence the model used internally.

The current `conversation_parity.py` builds `focused_property` from the current approved catalog before calling the SDK, and `_context_payload` serializes that context into the actual inference request. For the narrow synthetic property-type details questions, an extra read is therefore not a necessary measure of grounding. This is an explicit revision of the evaluation contract, not a change to production behavior or proof of the model's internal reasoning.

## Revised acceptance contract

- Observe the actual `TurnRequest` immediately before invoking the real runtime, for the expected current buyer message, channel, scope, and exactly one invocation. Verify company, project and lead identity, unambiguous property-type focus, reference, display name and queried numeric field against the same approved catalog input. For an ordinal, also verify the resolved visible choice.
- Require the completed persisted AgentRun for that inbound and inspect actual recorded tool observations. A successful `get_unit_details` read is supported but not mandatory when the same fact was already supplied. A rejected/conflicting details read is still a failure. No manufactured tool calls, model responses, state or receipts.
- Require the accepted outbound text to identify the correct property and state its correct bedroom/bathroom count; conflicting counts or another property name fail. Numeric and written counts and ordinary Markdown emphasis are supported for these synthetic questions. This targeted text test is not a general semantic verifier.
- Strengthen the synthetic fixture by using different bathroom counts (Van Buren 1; Oakwood 2), with the expected count derived from the actual second presented option. Both still have 3 bedrooms. No changes to real catalog or production configuration.
- Preserve all four real SDK scenarios, the same SDK pin/model and opt-in, PDF tool/receipt checks, search tool/menu evidence, idempotency and STOP assertions. The numbered-choice scenario still requires the two actual delivered options and exactly two AgentRuns.
- Export only fixed field names and booleans for fact evidence (`fact_grounding`); no raw context, IDs, URLs, secrets, or reply text. `verified_context` reports that the expected data was provided, not that a model's internal reasoning was observed.

## Validation performed

Exact hashes of the seven existing evaluation files and four relevant production modules, plus the price-reconciliation test were compared against the base GitHub tree (the new helper and test did not exist in the base). Local Python environment from the earlier API artifact, with current focal source and isolated SQLite:

- 203 previous HEI tests: passed.
- 147 remaining HEI and numbered-price tests: passed (115 previous HEI + 32 price reconciliation).
- 33 offline evaluation tests: passed (one existing end-to-end worker harness and 32 new controls).
- 7 existing sanitized diagnostic tests: passed.
- Total 390 locally passing tests. The offline E2E harness uses actual ORM, private ASGI endpoint and native dispatcher, with a simulated SDK/provider: one details response uses the verified request with no tool observation, one uses the actual details tool. Negative tests exercise incorrect scope, inbound, property, choice, fact, missing/duplicate invocation, rejected tool and incorrect accepted reply.
- `run_lane.py` now runs and counts the additional 32 controls in the offline lane (33 total). The four paid model cases are unchanged in count. No workflow changes needed.

Not run here: real SDK inference with OpenRouter, PostgreSQL rerun for this SHA, real Telnyx/Calendar, general regression, live rollout. The earlier run's PostgreSQL and frontend successes do not certify this new SHA. Production readiness remains CLOSED. No changes to production source, database or deployment configuration.

## Upload and reevaluate

Upload the eight files using their full repository-relative paths. Commit:

`test(hermes): certify focused catalog facts without redundant tool calls`

After the automatic CI passes, create a new manual `Hermes HEI-06 isolated evaluation` on `main`, mark `run_openrouter`, and check all four real SDK scenarios and the new grounding evidence. Do not use rerun on the previous SHA. Do not enable Hermes for live leads solely on the basis of four synthetic cases passing.
