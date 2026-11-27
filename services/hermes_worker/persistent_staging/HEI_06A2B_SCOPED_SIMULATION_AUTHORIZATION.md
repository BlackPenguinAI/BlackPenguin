# HEI-06A.2b.1 — Scoped Simulation Authorization

Base: `0eb7da1e8c675126f77ef94ddefa561cd2686246` (Persistent Foundation #4). Conversational parity baseline: `92769b0`. Private runtime baseline: `a61178b`.

## Scope and decision

This is a deliberately narrower first part of HEI-06A.2b. It activates the existing HEI-01B/P08 simulation executor in the persistent, attested staging topology, using the real SDK optionally. It **does not** enable `live_hermes_ready()`, route `SalesInboundJob` through Hermes, call `/internal/prepare` in live mode, or invoke the live provider dispatcher. The real commercial worker remains running and continues to see no commercial jobs from this lane. The queue is separate solely to avoid competing for or bypassing real jobs. The original P08 simulation path is reused; it is not the exact live path certified in HEI-06. No new LLM, graph, tools, or conversation repair rules are added. Full scoped authorization through the normal job/dispatcher flow is still a separate A.2b.2 requirement. Do not use this simulation queue as a production route.

## Upload Ready

All paths in the ZIP are relative to the repository root. Upload five new Python modules, this document, and replace the existing canonical `.github/workflows/hermes-hei06a2-persistent-staging.yml`. Do not upload a second workflow file or put this document at the repository root. No production files, migrations, provider secrets, or production deployment changes are needed.

Commit: `test(hermes): add persistent scoped simulation authorization`

1. Verify ordinary deployment and isolated evaluation.
2. Run **Hermes HEI-06A.2 persistent staging foundation**, branch `main`, `run_scoped=true`, `run_openrouter=false`.
3. If the offline run passes, run the same workflow with both inputs true. The existing `HEI06_OPENROUTER_API_KEY` secret is reused only in the scoped model process. With both inputs false, the original foundation lane runs unchanged. `run_openrouter=true` without `run_scoped=true` is rejected.
4. Inspect `initial.json`, `recreated.json`, `scoped.json`, `summary.json`. For failures, `scoped.json` carries the failed checkpoint, sanitized reason code or exception class and locations where available. No raw conversations or credentials are exported.

## Architecture and safety

- Fixed demo Company `stg-company`, Project `stg-project`, new test Lead `stg-hermes-lead` and simulation Conversation `stg-hermes-simulation`.
- `guard.validate()` and `guard.attest()` check the actual DB hostname, name, user, marker, instance and SHA at every command. Only local Docker operator authority is used; no new HTTP ingress, browser controls or API routes are exposed. This is not delegated staff authorization. Existing superadmin API remains the way to publish policy and inspect state.
- Grant is closed by default. One generation is valid for 60 minutes (checked before starting each turn), up to 12 queued events. An enabled, immutable published policy must use `openai/gpt-4o-mini` and a nonempty subset of `get_project_overview`, `get_unit_details`, `search_properties`, `compare_properties`. The currently certified foundation probe publishes the first two. No write/effect tool is granted, no native effect executor is invoked.
- PostgreSQL tables `hei06a2_scoped_grant` and `hei06a2_scoped_turn` are created only by explicit init inside attested staging. They survive container recreation. They are NOT part of production metadata or migrations. The message is synthetic, bounded to 4000 UTF-8 bytes, stored only in the isolated database. Event IDs must begin `hermes:staged:`. Do not submit personal information or real lead messages.
- Durable FIFO: `pending -> running -> completed` or `review`; pending work becomes `revoked` on revoke. Duplicate event IDs with the same content are idempotent within a grant; changed content or generation is rejected. A completed event is checked against its existing AgentRun, reply and state receipt, not reinferred. A crash after claim is not automatically retried. `revoke` marks uncertain running rows for review; the existing receipt may already be present.
- Grant row and global publication row are locked during the synchronous model turn in a separate transaction; publication changes and revocation wait for that turn. Lock acquisition is limited to 5 s. Revocation is not an instantaneous cancellation of an already executing turn. If it times out, stop the scoped SDK process/container, then revoke after restarting without egress. The claim/receipt transactions are separate; uncertain outcomes require review.
- The SDK container normally has only the internal private network. `process --model` creates a uniquely labeled temporary Docker bridge attached only to the SDK, passes the key to that exec process via environment and removes the bridge in finally. This is general outbound Internet access during that process, not a network-level OpenRouter allowlist. API/PostgreSQL remain private; SDK has no host ports. The existing SDK config restricts the provider to OpenRouter. No Telnyx, Calendar, Firebase or SMTP credentials are supplied. Production-grade egress allowlisting is still required before real-provider acceptance.
- The underlying staged runtime writes an in-app message and simulation receipt, not a provider receipt. This is a genuine SDK call if the model lane runs; it is not evidence of actual SMS/WhatsApp/Calendar dispatch. The test verifies persistence, scope, receipts, idempotent replay and inspector, not a second 18-case semantic benchmark.

## Optional operator commands (after CI approval, dedicated staging host only)

Keep the existing `manage.py` and certified topology. Use a clean checkout pinned to the exact candidate. State directory must be absolute and outside Git. Do not run on the production host. Example from repo root:

```bash
export PYTHONDONTWRITEBYTECODE=1
S=/absolute/path/to/private-stage-state
python3 services/hermes_worker/persistent_staging/manage.py init "$S"
python3 services/hermes_worker/persistent_staging/manage.py up "$S"
# In a fresh foundation, this publishes the restricted policy as part of probe:
python3 services/hermes_worker/persistent_staging/manage.py probe "$S"
T=services/hermes_worker/persistent_staging/scoped_manage.py
python3 "$T" init "$S"
python3 "$T" grant "$S"
# Create a file outside Git with a SYNTHETIC buyer message.
printf '%s' 'Tell me about Van Buren.' > /tmp/bp-synthetic-turn.txt
python3 "$T" enqueue "$S" --event-id hermes:staged:demo-001 --message-file /tmp/bp-synthetic-turn.txt
# Provide HEI06A2_SCOPED_OPENROUTER_API_KEY securely in the current shell.
python3 "$T" process "$S" --event-id hermes:staged:demo-001 --model
python3 "$T" status "$S"
python3 "$T" revoke "$S"
unset HEI06A2_SCOPED_OPENROUTER_API_KEY
```

`process` without `--model` will deny a pending event with no model key, or replay an already completed event without Internet egress. Use `manage.py stop` as emergency shutdown; it preserves PostgreSQL. A timed-out/cancelled model process may leave the labeled temporary egress network; verify that the network name is exactly this installation's `bp-hei06a2-<instance-prefix>_scoped_egress` and inspect its project label before disconnecting/removing it. Do not touch other networks. Revoke after recovering without egress. The original foundation `probe` assumes zero sales state and is only for a fresh foundation; use scoped `status` after the simulation lane has created receipts.

## Acceptance scope

Local tests verify fixed scope, demo/test consent, opt-out/pause, policy tools/model, closed gate, grant expiry/revocation/policy change, event identity. CI offline checks exact denial reason codes, queue FIFO, duplicate event handling, missing-key refusal, persistent grant/queue after recreation, zero commercial activity, inspector boundaries and revoke. Optional real lane runs two SDK turns, checks exact in-app receipts, replays the first without inference, checks inspector revision and revokes. The existing foundation tests remain prerequisites.

Local environment lacks Docker/PostgreSQL server and full repo checkout. Local tests used copies of previously recovered staging sources; full PostgreSQL, Docker, real SDK and actual HTTP inspector evaluation are pending CI. Production readiness remains CLOSED, real providers NOT_RUN, normal live worker routing NOT_RUN.
