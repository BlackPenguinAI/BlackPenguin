# HEI-02 — Conversation Parity (isolated Hermes lane)

Base commit: `c08ff0069960bd978390b61616282ea55d3ca3f7` (HEI-01B). Normal deployment run [45760049590](https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45760049590) completed successfully. The separately proposed SDK smoke workflow was absent from the base commit; the exact HEI-01B workflow is included again.

Commit: `feat(hermes): improve scoped conversation parity and delivered choices`

## Scope

This is an additive, isolated P04 preparation and receipt change used by the HEI-01B staged Hermes worker. No production selection change, migration, new database, provider call, Calendar booking, real asset issuance, onboarding or frontend rewrite. LangGraph and all its existing admin configuration remain intact. The readiness gate continues blocking live Hermes. This is an implementation candidate for conversational parity, not a certification of the real model's response quality.

| Behavior | Implementation |
|---|---|
| Property focus | Resolve unique approved commercial name or reference; preserve focus on implicit follow-ups and reject conflicting detail arguments. Multiple properties require disambiguation or comparison. |
| Property menus | Map consecutive visible numbered lines to actual search results in displayed order, including subset/reordering. Normalize an inline list only if all options can be verified. Bind the menu to the actual outbound message at receipt commit. |
| History | Read current channel/lead/project/activation only; exclude internal resume envelopes and unsent outputs. Keep up to 25 prior public messages. Invalidate menus and single media offers superseded by a later assistant reply. |
| Temporary search | Existing search and evidence-based preference writer remain authoritative. Prevent a model-only expansion of a saved hard budget; record current search criteria/scope without changing primary preferences. |
| Materials | Reuse P04 coverage/file checks. A single verified PDF candidate or a previously delivered unambiguous concrete offer can support a draft request. Multiple categories without a clear choice require clarification. Never issue real links. |
| Visits | Keep conversational property focus distinct from visit draft; use typed date/time menu's property for slot discovery. Continue using existing P04 validation, exact offer and recap requirements. |

## Remaining limitations and next gates

- The real pinned SDK and OpenRouter have not been executed locally. Neither the 25 new tests nor the previous 54 tests validate actual LLM responses. Parent port and choice/receipt contracts in the new focused tests are deterministic doubles, and the isolated history test uses SQLite ORM stand-ins. Full application regression and real staging journey remain required.
- Appointment receipt validators still require the exact property reference in the displayed visit menu/recap. Commercial display names are supplied to the model, but a full alias-aware receipt change and real booking/asset effects belong to HEI-03. Do not interpret a proposal or draft as confirmation.
- Multiple media categories can be discovered; this candidate supports explicit subjects and single verified offers, not a new numbered media-menu producer for all combinations. Existing typed choice resolver and slot checks remain in place. No unsupported generic document is fabricated.
- A prior LangGraph state is not copied into Hermes. Scope-checked conversation history may inform it; the focus/prefs are from the existing Hermes state and approved data. Do not claim complete migration or continuity for every historical case.
- No production database was inspected or modified. No real Telnyx/Calendar operations were attempted. Configuration and engine selection remain gated as in HEI-01B.

## Upload-ready files

| Path | Change |
|---|---|
| `backend/app/modules/hermes_sales_core/conversation_parity.py` | New scope-aware history, focus, search/menu and material draft adapter |
| `backend/app/modules/hermes_sales_core/bp_p04_turn.py` | Existing P04 default uses parity port; persist visible menu and offer only with reply receipt |
| `backend/tests/test_bp_hei02_conversation_parity.py` | Focused local contracts with deterministic doubles and isolated SQLite history |
| `.github/workflows/hermes-sdk-smoke.yml` | Reinclude missing HEI-01B workflow unchanged |
| `docs/hermes-integration/HEI_02_UPLOAD_READY.md` | This guide |

Upload at the repository root, maintaining paths. Include the hidden `.github` folder. No pre-upload script/patch/installation required. Use the commit above. Verify normal deployment and separate SDK smoke workflow (can also run with workflow_dispatch). Do not change engine selection or run the staging CLI against a production database.

## Test results

Local focused suite: 25 passed. Combined HEI-01A/01B/02 isolated suites: 79 passed. Python syntax validation. These are scoped local results with doubles, not the full repository CI. Existing baseline `bp_p04_turn.py` verified via Git blob hash `7f5d26baad95bde02ef575058255b9c77f971fcf` before modification. 

Suggested real staging acceptance journeys for HEI-02 / HEI-06 (not executed):
1. Ask for homes under a verified budget, choose the second displayed option, ask for details, request its PDF.
2. Ask about another property while a visit remains in progress, then return to the original visit; verify separate references.
3. Ask for cheaper alternatives, then revise budget explicitly; verify primary vs temporary criteria.
4. Repeat a conversation after process restart; verify current opportunity and delivered menu/receipt.
5. Ask for a PDF when the property has multiple verified materials; clarify the material type and keep focus.
6. Validate two date/time menus, select a date/slot, ensure the draft is not described as a confirmed appointment.

