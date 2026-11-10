# Lead controller v2: bounded buyer behavior, unchanged Sales engine

Base: aa9b1bd6ccf73fcec7d1d15866cf3691230c149a.
This delivery modifies evaluation tools and tests only. It does not modify Sales
runtime code, published prompts, model selections, fixtures or production data.
Replay and variants are fixed-message scripts and do not use a lead LLM; their
behavior is unchanged. Adaptive conversations use the new controller.

## What changes

The buyer LLM drafts messages for the current and next goal and describes its
perception of the latest visible seller reply. The backend owns advancement and
termination; there is no model-controlled `done` flag. Each goal has at most two
lead messages: a first attempt and one clarification/acceptance. A goal still
unanswered after that is recorded as unresolved, and the next goal is exercised.
Running out of turns or model-call budget leaves unexercised/unassessed goals
visible. Ending the controller does not turn a failed sales case into a pass.

The three scenario plans are explicit:

| Scenario | Ordered goals |
| --- | --- |
| new_buyer | Available types/prices; bedrooms and floor area of the named type; budget/cash only if asked |
| targeted_materials | Photos and PDF for the named type; parking confirmation |
| continuity | Named property's price/availability; cash declaration; explicit change to bank financing plus bedroom question |

Floor area never intentionally turns into neighborhood research. Material cases
need not have three artificial lead turns after two goals have been addressed.
Cash and payment-change drafts have additional goal checks; a vague "considering"
change cannot replace the explicit change required by the scenario.

Drafts are bounded in length and screened for known seller-role expressions,
near repetitions, neighborhood drift and out-of-scope content. A rejected draft
is not sent: a short goal-specific backend question/declaration replaces it,
with a rejection reason and fallback source in the audit. This is an observable
recovery, not an unlogged claim that the LLM generated the final text. The lexical
screen is not a semantic guarantee of role correctness; inspect raw transcripts.

An answered/unavailable perception must quote the latest seller reply verbatim.
A historical quote, fabricated quote or repeated "which property do you mean?"
cannot advance a goal as answered. Explicit unavailability may close a buyer's
question, but does not override actual resource/coverage assertions. The lead LLM
never receives approved-context internals, database rows, planner output or audit
traces. It still sees only the synthetic profile/goal instructions and public chat.

The last seller reply can receive an assessment-only model call. It sends no extra
message to the Sales engine and uses the same global call budget as other calls.

## Metrics and comparison

Each case now contains `lead_controller` and each generated turn identifies its
goal, attempt number and draft source. JSON and Markdown expose goal outcomes.
The project and laboratory summaries include `lead_controller_metrics`:

| Metric | Meaning |
| --- | --- |
| finished | All goals reached a bounded terminal outcome; not sales success |
| perceived_resolved_cases | Buyer judged goals answered/unavailable, supported by visible quotes; not independent factual grading |
| unresolved_goals | Still unanswered after both attempts |
| unassessed_goals | Budget/turn/error limit left final response or remaining goals unassessed |
| seller_drafts_rejected | Seller-role drafts intercepted before delivery |
| repeat_drafts_rejected | Near-duplicate drafts intercepted |
| goal_drift_drafts_rejected | Neighborhood drift intercepted |
| fallback_messages | Backend goal-specific replacements actually used |
| max_goal_attempts_observed | Highest number of lead messages used by any goal; must not exceed two |
| role_violations_delivered | Delivered lead messages matching the same role screen; target zero |

`scenario_completed` still fails when goals remain unresolved. Existing sales
interpretation, composition, current workflow, resource scope/delivery and safety
assertions are unchanged. A case may have finished=true and scenario_completed=FAIL.

The previous run had 51 lead turns and only one of nine scenarios completed.
The former arbitrary three-turn minimum is replaced with plan completion, so raw
PASS counts and completion rates are not directly comparable without reading goal
outcomes. Compare repeated lead content, role errors, tested goals, unresolved
sales needs, sales assertions and cost together. No live improvement is claimed
from the offline tests. Keep both lead and Sales models unchanged for this run.

## Run after deployment

Only rerun the synthetic lab to measure this change; replay and variants have no
lead controller. Use the existing published model for both roles, with no override:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 180 --max-turns 6 \
  --output /tmp/sales-synthetic-lab-3

docker cp bp_api_prod:/tmp/sales-synthetic-lab-3/synthetic-sales-results.zip ./sales-synthetic-lab-3.zip
```

A FAIL result is useful diagnostic evidence. Copy the output regardless of exit
code 2; execute the commands separately. The budget includes decision/final-review
calls, Sales inference/repairs and any optional judge. No judge is enabled here.
Inference consumes OpenRouter credit; no messages are sent to real leads and no
production commercial records are written.

Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-synthetic-lab-3.zip "$env:USERPROFILE\Downloads\sales-synthetic-lab-3.zip"
```

The report records actual selected models and the controller version so comparison
with sales-synthetic-lab-2.zip can check that the model/configuration stayed fixed.

## Local verification

Backend regression across all three shards: 2525 passed, zero failures and seven
skipped; partition verification covered all 110 modules exactly once. Final
focused controller, lab and evaluation checks: 55 passed, including the final
conditional-qualification regression. Acceptance: 63 PASS, zero FAIL and one
real-model/channel case NOT_RUN. All inference responses were scripted offline;
the new live conversation metrics must be measured after deployment.
