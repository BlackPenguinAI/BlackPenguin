# HEI-06 — Numbered catalog price reconciliation

Base: `2063716760e20f7417668022193eb06e766a339e` (main). Evaluation run [#6](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45923555574).

## Observed result

Both `focus_pdf` repetitions passed with the actual pinned Nous SDK and OpenRouter (synthetic catalog, test database, doubled provider). Both `numbered_choice` repetitions executed `search_properties` successfully, produced two numbered lines mentioning Van Buren and Oakwood, then failed during private preparation with `ProductionToolError` / `monetary_guard`. Neither scenario reached the second-option turn. The original sanitized trace contains no exact rejected monetary expression; it does not prove whether the model produced an incorrect price, an abbreviated price, or echoed the requested budget. Do not diagnose the API key or the ordinal resolver from this failure.

With the unchanged shared validator and synthetic approved starting prices USD 325,000 and USD 340,000, the following independent reproductions fail:

- A header repeating the requested ceiling `under $350,000` above otherwise valid catalog prices. The ceiling is not an approved catalog price, and this search need not persist it as a primary budget.
- `$325k` / `$340k` (abbreviations not accepted by the strict monetary parser).
- Prices assigned to the wrong property or invented amounts.

Full explicit prices with the correct property pass. These are reproductions, not the recovered model output from run #6.

## Change

`numbered_catalog.py` provides bounded, deterministic presentation reconciliation when the existing monetary check rejects the live model reply. It requires a current authenticated turn with a successful `search_properties` observation, exactly one unambiguous property menu independently re-proven against the same turn's search rows and rendered text, and no other tool activity, media offer, mixed request or multi-message resume. It does not infer a new search or reorder or add options. It quotes approved prices from the same snapshot, with explicit currencies, full amounts and accurate starting/listing-price wording; includes known bedroom count; asks which option the buyer wants to explore. Explicit supported budget and bedroom constraints are checked again. No unknown price, unknown property, contradictory buyer filter, mixed-effect operation, ambiguous or oversized list is repaired. This path also supports ordinary search questions that did not explicitly request numbering.

`live_preparation.py` applies the repair only after a monetary rejection, repeats the **unchanged** shared monetary validator (requiring affirmative evidence of monetary checking) and the existing language and delivery checks on the new text. The newly rendered menu must preserve the original references in their actual displayed order. The immutable prepared draft, dispatcher, state CAS and provider-receipt binding are otherwise unchanged. The dispatcher independently revalidates commercial data before sending. The state menu becomes actionable only after actual acceptance. No second model invocation, no native effect, no primary preference write or fallback to LangGraph is added by the repair. No change to LangGraph's shared `monetary_policy.py` or to the global readiness gate.

This is deliberately a narrow presentation repair, not a replacement of the SDK with a rule-based conversational engine. Unprovable or mixed requests and prices still rejected by the guard remain in review. The fix does not establish that all monetary guard failures are recoverable or that the original two specific outputs are known. The actual real-model four-case evaluation must run again unchanged.

## Verification performed

The prior release API archive (`f00049e`) was extracted, its inner image tar checksum checked, and the original modified source and existing test files were compared to the current GitHub blob hashes. `live_preparation.py` original `914e35b9d5afc7e591285b2c98c4bb17b8a1932c`; `test_harness_offline.py` original `8fc7fbbd838f3a61c0298c6b51e26276d824de6a`. All twelve earlier HEI test modules, plus the relevant unchanged validator, response renderer, search port and parity module, matched current GitHub blob hashes.

- 22 new targeted test cases passed: rejected budget echo, abbreviated prices, swapped/invented values, reversed model-selected order, stale scope, foreign/duplicate reference, failed/mixed tool observations, media/mixed request, wrong bedrooms/currency, over-budget/boundary cases, unknown prices, and fresh guard rejection after catalog drift.
- Existing offline harness now exercises the rejected budget echo and abbreviated amounts using the same real scoped ORM/worker/private FastAPI ASGI path with a doubled SDK and message provider. The accepted SMS contains approved full prices; the visible menu is persisted and the second-option details turn resolves correctly. Existing PDF, replay and STOP checks remain intact. Harness passed 1/1.
- Final grouped Python regression with Python 3.12 and installed dependencies extracted from the API image: 203 passed, 22 warnings; 138 passed, 2261 warnings. Total 341 = 318 previous HEI + 22 new + 1 offline E2E harness. Isolated SQLite. Initial chroot capture failed because the extracted image lacks /dev/null; reran with pytest `-s`. No application failure from that infrastructure issue.
- Real OpenRouter scenarios not rerun here; PostgreSQL, Angular and real external providers not re-executed locally in this delivery. Existing CI lanes will repeat the candidate checks. The four actual OpenRouter scenario assertions, model, SDK pin, workflow and secret remain unchanged.

## Upload / re-evaluation

Upload the full files from this ZIP preserving repository-relative paths using GitHub Upload Files. Commit: `fix(hermes): reconcile rejected numbered catalog prices from verified search results`.

After the normal deployment and automatic offline evaluation succeed, start a **new** manual workflow from [Hermes HEI-06 isolated evaluation](https://github.com/BlackPenguinAI/BlackPenguin/actions/workflows/hermes-hei06-evaluation.yml), branch main, with `run_openrouter` checked. Do not rerun run #6 (old SHA). Existing `HEI06_OPENROUTER_API_KEY` is unchanged. No additional secret, migrations, setup scripts or workflow file are needed. Verify the new SHA and the four original real-model scenarios. Real Telnyx and Google Calendar acceptance, the private network service, actual published policy and rollout/rollback certification remain outstanding. Production readiness stays CLOSED; LangGraph remains the live engine. No direct repository/deployment/database write was performed.
