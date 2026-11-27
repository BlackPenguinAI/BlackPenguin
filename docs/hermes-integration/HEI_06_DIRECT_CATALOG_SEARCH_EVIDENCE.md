# HEI-06 — Direct catalog search evidence and stable numbered presentation

Base: `2090dfdf91f927908eaa8b28b42ed2fc97cee28d`.
Run: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45933715693 (#12).

## Evidence and root cause boundaries

The supplied sanitized report records both focus/PDF scenarios PASS, numbered choice repeat-1 PASS, and numbered choice repeat-2 FAIL before dispatch with monetary_guard after two successful search_properties observations. It does not contain actual tool arguments, the search results or the rejected price expression. Thus it does not prove why the original reconciliation returned None. Inspection confirms two independent weaknesses: ParityOperationalPort retains only the last search result, and the original reconciliation requires a previously bound menu. A synthetic reproduction now invokes a verified search for three-bedroom properties at USD 350,000, a project overview, and a narrower search at USD 330,000, with formatted numbered output. The exact query has two approved matching rows while the later search has one. The new contract preserves the first result for the explicit buyer request, renders a valid menu and resolves the second property through the actual worker.

## Scope and behavior

- Keep a turn-local ledger of successful authorized search results and their effective search criteria and source inbound ID. Never use a result from a different turn, tenant, project or conversation. Nothing is added to the database schema.
- Only for direct, explicitly numbered catalog-list requests specifying exact bedroom count and a USD upper budget, with the narrow supported grammar, use the latest complete single batch that exactly matches the buyer's request (including equivalent exact filter bounds), even if a later model exploration was different. Require positive verified inventory, 2–9 returned entries, no duplicate references, all rows within the stated filters, successful search observations corresponding to the ledger, and no mixed operations or rejected tools. No merging across batches, new search or extra model call.
- Preserve model order if every selected reference can be proven on the channel-normalized text and the full batch is represented. Otherwise publish the approved batch order as a new menu; never send the unproven model options. The original monetary and language guards still validate the reconstructed reply; an invalid reconstructed reply is rejected. The selected search's actual state is committed only after accepted delivery. No new operational authorization. Outside this narrow path the existing general reconciliation and fail-closed behavior are preserved.
- Real evaluation now reports allowlisted catalog_reconciliation events (applied, search_batches, fixed reason codes), not raw claims, tool arguments, prices, customer text, URLs or credentials. No test assertions or case counts in the four real SDK scenarios have been weakened. The existing offline harness remains one test and exercises the new multi-search path.

## Local validation

Used the existing isolated Python image environment with source files checked against the candidate Git tree. No production database, real provider or real OpenRouter call. SQLite and SDK/provider doubles where appropriate.

- 203 prior HEI tests passed (01A–03B.2).
- 115 prior HEI tests passed (03B.3–05).
- 102 passed in the reconciliation, offline worker harness, focused fact grounding and diagnostic suites (61 reconciliation, 1 offline harness, 32 grounding, 8 diagnostics).
- Total: 420 passed, 0 failed across those invocations. 29 new reconciliation cases and 1 new diagnostic case relative to the previous 390 locally reported tests.

The real OpenRouter four-case lane, isolated PostgreSQL and general repository regression still need execution on this candidate. This does not certify Hermes for production. Keep readiness closed until external acceptance, private HTTP transport, actual published policy and rollback are certified. No workflow, secret, dependency, DB migration or engine-selection change. Upload full files at their relative paths. Start a NEW manual HEI-06 workflow run with run_openrouter checked on the new commit. If it fails, inspect the new catalog_reconciliation events and the full sanitized evidence rather than repeatedly rerunning the same candidate or weakening assertions.
