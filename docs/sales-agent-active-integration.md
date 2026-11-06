# Active Sales dialogue integration

Base commit: `e96c8189cfd39f351274d9f2add115ffc59eecf1`.

This delivery closes the production inbound bridge, rather than treating the
new runtime as shadow output. Historical group documents describe earlier
deliveries and are retained unchanged as evidence.

## What actually executes

For an enabled, published active cohort, `process_live_inbound` calls
`active_service` before legacy graph classification or scheduling continuations.
The coordinator loads opportunity-scoped state and the latest actual offer,
obtains schema-validated understanding using the published Sales model and
guidance, resolves references, builds tasks and restrictions, executes bounded
read tools, reconsiders alternatives/fallbacks, composes verified facts, performs
authorized domain actions and saves a durable prepared response. Existing
channel rendering/outbox then sends that response. Provider acceptance is
recorded separately from confirmed delivery. Active errors never silently
switch that event to the old graph.

The loop is a bounded task/tool loop, not eight LLM calls. Composition uses
deterministic verified facts; the LLM interprets requests rather than inventing
the final answer or issuing effects directly. Greetings, missing facts and
invalid model output do not by themselves pause a conversation. Protected
control requests work even when the model is unavailable.

Material delivery uses approved IDs and fresh permissions, not text-based
asset selection. AND can supply multiple relevant files; OR selects a suitable
branch. Unverified embedded photos require assent to the named fallback file.
Approved files can satisfy part of a mixed request without claiming full
coverage. Requested virtual-tour links are rehydrated from approved resources
and issued through the audited share service, not copied from model output.

Booking uses the existing location, eligible-sales, locking, availability and
round-robin services. The booking and prepared response commit before Google
Calendar is called. Calendar retries use a stable event ID and a bounded worker
sweep of active-source bookings; legacy bookings are not swept. Cancelling a
meeting or disabling its cohort stops new sync attempts. Follow-ups for active
cohorts use a non-effectful continuation prompt, not the old graph.

## Activate before manual E2E

Deploy this differential on its base (or reconcile newer changes first). No new
migration is introduced; existing dialogue tables from the preceding groups
must already be migrated.

1. Set repository **Actions variable** `SALES_DIALOGUE_RUNTIME_ENABLED=true`
   in GitHub Settings → Secrets and variables → Actions → Variables.
   The deployment workflow validates and persists it to the common API/worker
   environment on every deployment. If absent, the safe default is false.
   Run a new successful deployment so both containers receive the setting.
   `SALES_UNDERSTANDING_PREVIEW_ENABLED` may remain false for active execution.
2. Open `/admin/ai-settings`, Sales Agent. Select the configured model and ensure
   the Company has its normal configured model credential.
3. Set runtime Mode to **Active · structured engine** and Scope to
   **Global · all Companies and Projects**, save and **publish**. Global includes
   future Companies/Projects and requires no IDs. It does not bypass consent,
   sales authorization, paused conversations, approved assets or tenant isolation.
   A draft alone is not activation. For a restricted test instead, choose Cohort
   and supply canonical Company/Project UUIDs and optional Lead UUIDs, never `*`.
4. Use a consenting test lead on the normal live messaging path. The historical
   simulator still has its separate legacy simulation executor; do not use it
   as proof of the new inbound engine.
5. In `/monitor`, confirm outbound metadata shows `sales-active/1.0`. JSON
   diagnostics retain understanding, constraints, task state, model/prompt
   snapshot, prepared actions, dispatch text and provider status. Staff-only
   monitor/export permissions and redaction are retained.

Verification on the server (read only):

```bash
docker exec bp_api_prod printenv SALES_DIALOGUE_RUNTIME_ENABLED
docker exec bp_worker_prod printenv SALES_DIALOGUE_RUNTIME_ENABLED
docker exec -i bp_postgres_prod psql -U postgres -d blackpenguin_db -P pager=off <<'SQL'
SELECT ar.started_at, ar.graph_version, ar.status, ar.error_code,
       ar.output_snapshot->>'engine' AS engine,
       ar.output_snapshot->>'reply' AS reply
FROM agent_runs ar
ORDER BY ar.started_at DESC LIMIT 15;
SQL
```

If the flag is false or the published cohort is not active, new events still
use legacy. Prepared active events remain sticky and are not reinterpreted by
legacy on rollback. Re-enable the cohort to resume a safe prepared retry, or
resolve it operationally. Disabling does not undo already sent messages or
confirmed meetings. No automatic publishing or production activation is done
by this patch.

## Manual scenarios

- Catalog with more than three types; choose a number; verify only that type's
  detail and stable identity even if sorting changes.
- Photos OR brochure + financing + explicit refusal of visits: one appropriate
  material branch, financing answer, no scheduling.
- Brochure AND plans: all relevant approved files, no unapproved resources.
- Photo request with only a broadly labelled brochure: name the fallback and
  wait for assent; do not pretend that photo coverage is confirmed.
- Ask for a 360 tour and validate the audited destination.
- Ambiguous number without a current offer: clarify, do not send/book.
- Explicit appointment, location choice if needed, verified time choice: one
  meeting and a truthful confirmation; provider retry must not create another.
- Missing prices/inventory: answer known information and retain missing needs;
  do not fabricate values or pause automatically.
- Human request/opt-out/manual takeover: stop automation and retain the reason.

## Test boundaries

Automated integration tests use the real coordinator, SQLite persistence,
approved-resource lookup and outbound dispatcher. Model inference and network
transport are scripted/mocked, not real provider calls. Existing regression
suites cover onboarding, catalog, governance, scoped diagnostics and delivery.
These results do not certify model interpretation quality in unrestricted
language, PostgreSQL concurrency, provider receipts or Google OAuth in your
deployment. Manual live E2E remains required; no real SMS/WhatsApp, model or
calendar calls were made as part of this delivery.
