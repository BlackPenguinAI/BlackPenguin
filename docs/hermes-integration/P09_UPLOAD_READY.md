# P09 — guarded foundation: real country routing, scoped deletion & opportunity discovery

**Base SHA:** `0a06c9be28f95a411600aa1d14f4609655f715cb` (P08, `main`).

**Intended delivery:** upload the *contents* of the ZIP to the GitHub web Upload Files page, keeping repository-relative paths. Do not run any patch/apply script before upload. Only the files present in the ZIP are changed.

## Implemented in this differential

1. `messaging_gateway.py` selects the actual live channel by supported destination country when `destination_phone` is supplied: +1/NANP→SMS, +51 Peru/+52 Mexico/+54 Argentina→WhatsApp. If that channel is unavailable, it returns **no channel**, never a simulated fallback. A legacy `requested='sms'` cannot override a supplied Peru/Mexico/Argentina destination.
2. The Meta webhook no longer hardcodes `preferred_channel='sms'`. It records source form evidence under the destination-selected channel and delegates activation to a **real-only** entrypoint.
3. `p09_live_entry.py` uses the existing production provider dispatcher for Meta leads only after the country route is verified. An unavailable route sets `agent_status='routing_blocked'` and issues a tenant-scoped notification, without creating synthetic conversations, simulated agent runs or delivery receipts. A separate in-app simulation API remains available as an explicitly invoked internal test tool; it is not a fallback for Meta leads.
4. `p09_opportunities.py` returns limited active opportunity summaries for a phone **within exactly one Company**, preserving Project A and Project B as separate Leads and not exposing Company C2. It does not transmit conversation contents, old choice menus or meeting secrets to the LLM. A staff-only read endpoint exposes this view for auditing.
5. `p09_delete.py` provides Staff Superadmin-only deletion previews and a **guarded** physical deletion endpoint for isolated leads or contacts within one Company. It rejects legacy threads containing more than one opportunity, in-flight sends/runs and outstanding Google Calendar references. It leaves immutable minimal audit evidence, strips retained provider webhook payloads and deletes local meeting files after DB commit. Deletion is **disabled by default**, requires `BP_P09_HARD_DELETE_ENABLED=true` after a controlled PostgreSQL acceptance and reconciliation plan.

## Not yet complete — do NOT interpret this as all of P09

- **P09-A full migration**: existing `live_service.get_or_create_live_conversation()` still reassigns a physical conversation when a second Project becomes active. The new read-only opportunity summary is not yet an automatic Hermes project-focus switch. Historical shared conversations require a safely attributed migration before physical deletion can be enabled. The current hard-delete endpoints deliberately refuse them.
- **P09-B production enablement**: delete remains off. There is no irreversible deletion path accessible via ordinary Admin UI. Calendar events must be externally reconciled first; the deletion implementation does not directly call Google Calendar. Provider in-flight operations, other worker race windows and retention requirements require production acceptance.
- **P09-C all legacy entrypoints**: the Meta webhook and manual live-lead creation are country-gated, but the original legacy `live_service.launch_live_lead()` still contains a simulation fallback when called from other old paths. Do not claim that all legacy paths are fully migrated to real-only behavior.
- **P09-D real integration**: SQLite guard tests do not substitute for PostgreSQL FK cascade tests, provider sandbox receipts, Google Calendar verification, or webhook race testing.
- **NANP +1**: currently matched as SMS according to the existing +1 policy; this is not a full international numbering library, and +1 can include countries beyond the US.

## Proposed acceptance gates before enabling deletion

- Real PostgreSQL: verify P07/P08 gates still pass, then test each FK cascade, immutable audit record and file deletion.
- A→B within C1: register two leads, confirm both are discoverable; **do not** delete until the shared physical thread has been migrated to independent conversation records.
- C1 vs C2: same phone, different Company and sender; reads, deletes and provider dispatch must never cross Company.
- Provider: unsupported/unverified route must not insert a simulated conversation/message; route-by-country must match the approved policy.
- Calendar: deleted lead has no active external Google event; verify provider failures and retries before enabling.
- Replays/concurrency: new lead with same phone after deletion must not inherit old messages, menus, offers, state or provider webhook replays.

## Commands after upload (optional, for CI/review; nothing to run before upload)

```bash
cd backend
python -m pytest -q tests/test_bp_p09_country_routing.py tests/test_bp_p09_hard_delete_guards.py tests/test_bp_p09_opportunities.py
```

## Suggested commit

`feat(sales): stage P09 tenant-safe deletion and country-based live routing`

These changes are intentionally conservative. The remaining migration/cutover must be reviewed and shipped as a **separate differential** rather than silently deleting shared production data.
