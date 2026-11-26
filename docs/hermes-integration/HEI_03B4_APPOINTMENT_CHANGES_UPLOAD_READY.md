# HEI-03B.4 — Native appointment changes and multi-subject materials

## Baseline and upload

- Repository: `BlackPenguinAI/BlackPenguin`, `main`.
- Exact base: `3cd1c7a70ab4c2c656e273e71d9e1c2ede6e79fc`.
- Successful deploy: https://github.com/BlackPenguinAI/BlackPenguin/actions/runs/45832717816
- Commit: `feat(hermes): integrate native appointment changes and multi-subject materials`
- Unzip and upload the complete files with paths preserved. No patches or pre-upload scripts. Upload `.github/workflows/hermes-sdk-smoke.yml` individually if the hidden directory is omitted.
- No DDL, migrations, configuration changes, provider credentials, server commands or direct GitHub changes are required for this delivery.
- Keep `live_hermes_ready()` false. Do NOT start the private Hermes runtime against production or change the global engine yet.

## Implementation

### Live changes

`live_changes.py` uses the exact same-project, same-lead active future Meeting snapshot and existing native reservation transactions. The SDK tool makes a read-only draft, with a backend-rendered recap. The cancellation path requires a direct request (e.g. `Please cancel my visit.`), an accepted exact recap, and separate explicit assent. A replacement request must select a currently offered date and hour (e.g. `Please reschedule my visit to 2026-12-02 at 10:00.`), for the same property, project, timezone, location and 60-minute duration. The previous slot offer must have a real provider receipt. The new time must be fresh and still available. The existing replacement transaction preserves the original if the new reservation cannot be made. Current and pinned tool permissions, the scope, current buyer consent, latest message/revision, and evidence are checked at execution. A historical receipt is replayed without executing the same action again.

The existing `cancellation_service.cancel` and `reschedule_service.replace_visit` accept an internal optional authorization callback, defaulting to the original authorization. Hermes supplies `authorize_native_change`; legacy callers are unchanged. The existing native booking/cancellation/reschedule operations and notification outbox are used. No LangGraph planner or dialogue state is invoked by this change executor; a transient state object supplies the existing native functions' proposal-clearing and cadence-stop fields. The Hermes state and native receipt are committed together. Confirmation text is reconstructed from native receipts, and the provider boundary validates that text again. No confirmation claims external Calendar synchronization. No direct Calendar call to create/delete a reservation is added.

Supported initial scope is intentionally narrow: one future active visit in the current project, with a verifiable snapshot, same property and location for replacement, and explicit English date/time and assent. Multiple active visits, cross-project changes, ambiguous phrasing, unapproved locations and stale recaps are denied/reviewed rather than guessed. The test suite exercises a simulated provider; actual Google Calendar free/busy and effect synchronization remain to be certified with external credentials in isolated staging.

### Multi-subject materials

`live_multi_material.py` builds an ordered, deduplicated mapping from asset IDs to explicitly requested subjects. Example: `Please send me the brochure and floor plan for Van Buren.` All requested types must be present, bounded to 20 assets, and approved for the exact property and actual channel. Alternatives, negation, conditional or quoted requests are not interpreted as multi-file consent. `production_tools._material_batch` rechecks each asset/subject coverage and current file snapshot, then reuses the existing issue/dispatch/reconciliation flow. Single-subject requests remain supported. No new tokens are written to Hermes operation receipts. No external URL-gallery support is added by this change.

## Validation

- Downloaded the successful API release artifact (ID 15123685104); ZIP SHA-256 `3554564b4a206fc3436edca76f92d5f255b3855c19b80c0583de405afff2cee4` matched GitHub and the internal `api.sha256` verified.
- Extracted application code from the exact image. All nine modified API module original blobs and the original SDK smoke script matched GitHub tree hashes. All seven prior HEI test files used locally matched GitHub hashes.
- Executed using Python 3.12.16 and the installed dependencies from the earlier HEI API image, with the current application source and isolated SQLite. Prior regression and new tests: **241 passed, 722 warnings in 17.40s**. 21 new tests, 220 prior tests. Warnings are not failures; the output includes existing datetime and ORM deprecation warnings.
- The new suite uses actual ORM, native scheduling, cancellation/replacement, asset share and dispatcher code. SDK inference and messaging provider are test doubles. Tests cover cancellation and replacement success/replay, failed replacement preserving original, stale snapshot and altered recap, ambiguous/negated requests, material batch mapping and native issue/dispatch with two material types.
- No full backend/Angular CI suite, real SDK/OpenRouter inference, PostgreSQL integration or actual provider/Calendar calls were performed locally. The private runtime is not deployed. The independent SDK smoke workflow was again absent from the base tree and is included here; upload and verify it separately if necessary.

## Remaining gates before HEI-03 can close

1. Hermes-native resume after human control (existing internal resume envelope has no real provider ID; do not fabricate one or invoke legacy coordinator).
2. Scheduled followups and inactivity (existing jobs are rejected by Hermes router; preserve explicit STOP/consent, epoch, scheduling policy and WhatsApp window).
3. Multipart provisional conversational replies (native material groups already supported; ordinary provisional replies still single-part). Must bind choices to complete accepted ordered groups without synthesizing provider rows.
4. Broad conversational qualification/profile support beyond explicit budget/bedrooms, ambiguous/multiple visit handling, and external approved galleries.
5. Actual SDK, private service and isolated PostgreSQL/provider/calendar integration. Preserve default LangGraph until HEI-06/07 certification.

HEI-04 Inspector and HEI-05 Admin Panel remain next after the remaining HEI-03 routing/continuity work. This delivery does not claim completed production activation or full conversational parity.
