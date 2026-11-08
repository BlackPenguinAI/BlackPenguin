# Active Sales: connected lead journey

Base: d905c635d594c18c5e3dae830594a02fc0bb4dfb (the confirmed deployed recovery patch).
Copy backend/ and docs/ over that repository. No migrations, dependencies or frontend changes.
Do not apply this ZIP to an older version without the preceding recovery/onboarding changes.
No deployment, runtime activation, production data rewrite or real provider call was performed.

## Connected behavior

- Location reads the canonical approved address/city/country, including legacy address lists without raw JSON.
- Selected property context applies to price and inventory as well as details/materials. Inventory/price offers
  retain the displayed IDs so ordinal selections can resolve against the actual outbound offer.
- The interpreter receives scoped approved Company guidance, approved Project strategy and existing lead
  qualification data. Draft Company guidance is excluded; published revisions remain authoritative.
- Interpretation prompt 1.3 captures explicit timeline, financing, buyer type and visit-readiness preferences,
  alongside existing budget/property/bedroom/location preferences. Old persisted interpretations remain valid.
- Qualification facts retain exact inbound evidence and message ID rather than trusting a model's normalized
  monetary value. Approved catalog selections are stored as property interest. These are lead declarations,
  not externally verified financial facts, appointment consent or approval to share materials.
- A deterministic planner recognizes budget, purchase timeline, financing, property type and visit readiness
  in approved qualification_rules (common English/Spanish labels). It asks one not-yet-asked missing item per
  eligible turn, without interrupting appointment handling, clarification, material delivery or opt-out/handoff.
- Asked fields and collected facts persist in the lead profile. Unanswered questions are not automatically
  repeated every turn. Collecting an answer is not declaring the lead qualified or financially eligible.
- Accepted, non-paused active turns update the existing score/segment/objection system. Active scoring reads
  the published scoring config directly without the mutating configuration accessor. Durable retries do not
  repeat scoring. Scheduling and handoff retain ownership of terminal workflow states.
- Pending automatic cadence follows the updated tier; follow-up wording uses a missing qualification item or
  the selected approved property. Processing failures do not schedule a new cadence and cancel pending
  automatic cadence, while preserving unrelated pending jobs.

## Policy boundary

Platform permissions/safety always win. Company restrictions cannot be waived by Project or lead messages.
Approved Project-specific or Company-specific free-text compliance holds the affected action for Sales review.
It does not create a blanket conversation pause or a human intervention case merely because notes exist. Scheduled active follow-ups are cancelled while such restrictions exist.
The explicit standard-Company/no-Project-specific-notes choice alone does not require handoff; real Company
restrictions still apply. Unknown free-text policies are NOT silently executed as legal instructions.

This conservative action gate can hold commercial actions for existing custom-compliance Projects while the
conversation remains active. Review the approved guidance with the Company administrator before rollout. We did not add a UI for compiling free-text policies into executable rules.
Arbitrary qualification rules beyond the recognized categories are not an automated eligibility engine.
Existing scoring remains heuristic and is not proof of budget fit, loan approval or purchase intent.

AI Settings remains the source for model, scoring weights, cadence, runtime cohort and concise/detailed style.
The final reply remains grounded deterministic composition, not unrestricted generative copy following every
free-text brand/tone instruction. A full multilingual/style generator is not included in this patch.

## Regression and acceptance

The new coordinator tests replay catalog -> qualification -> property selection -> selected price -> canonical
location -> human handoff. They also cover compliance action holds without booking or conversation pause, Company restriction
precedence, low-confidence answers, unchanged runtime config, personalized follow-up and cold-to-hot cadence.
Existing tests exercise materials, STOP, explicit restrictions, appointment confirmation, calendar retry,
tenant scope, manual takeover, recovery and duplicate-delivery prevention.
The coordinator journey mocks model, delivery and cadence scheduling; a separate test exercises the
real cadence helper. State/CRM persistence runs locally. No real contacts were messaged.
Full backend: **1453 passed, 2 skipped**. git diff --check passed.
Results are in delivery/backend-tests.log. No frontend build or real-model acceptance is claimed.

After deployment (operator action), test with an explicitly consented test lead:

1. Ask for available properties; receive approved facts, not invented stock.
2. Answer budget/timeline/financing; verify evidence, score and next missing question persist after reload.
3. Select an option, ask its price, then location. Confirm no other option's price is substituted.
4. Request approved photos/materials and explicitly request/confirm a visit; check human assignment,
   availability, timezone, booking and Calendar status. A qualification answer alone must not book.
5. Retry an inbound job only in an isolated test environment; verify no duplicate send/booking/score snapshot.
6. Check STOP, human takeover and custom-compliance action holds. Paused conversations must not send automatic cadence; custom compliance still suppresses proactive cadence pending review.
7. Inspect prompt version 1.3, qualification_offer/qualification_missing metadata and intelligence records.

Real OpenRouter/Telnyx/Calendar behavior and production UX remain acceptance work in your environment.
Historical conversations and previously failed messages are not automatically replayed or rewritten.

The conversation continuity and administrator review changes are described in `sales-conversation-continuity-review.md`.
The test counts above describe the preceding ZIP; see the current delivery manifest for this patch.
