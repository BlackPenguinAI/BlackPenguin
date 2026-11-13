# API responsiveness during Sales processing

## Incident and evidence

On 13 November 2026, revision `84b3a8767bdb8d716319caf7d3a6acdc620cbcf7`
had an unresponsive API while the frontend remained responsive. PostgreSQL
showed an idle transaction holding the conversation lock and another request
waiting for that transaction. Restarting the API restored health endpoints.
The affected inbound job subsequently completed on attempt 2 and its outbound
WhatsApp message acquired provider status `delivered`.

This evidence establishes recovery for that message, not a permanent repair.
The code exposed a circular wait: synchronous webhook SQL could block the API
asyncio loop while the lock-owning Sales coroutine needed that loop to finish
its model request and commit.

## Change

| Boundary | Behavior after this change |
| --- | --- |
| Signed Telnyx/Twilio webhooks | Read body/form asynchronously; execute database handler in FastAPI's thread pool. Signature checks and tenant routing remain in the existing handler. |
| Inbound and follow-up jobs | Pass only the job ID into a worker thread with a private asyncio loop; the handler owns and closes its sessions. Job processing remains serial. |
| Job wrapper | Capture conversation/message IDs before commit so expired ORM attributes do not reopen an idle transaction during the child turn. |
| Sales/provider transactions | PostgreSQL lock waits are bounded to 2 seconds. Idle transactions are bounded to 120 seconds. Settings are local to each marked transaction and reapplied on the next transaction. |
| Webhook lock timeout | Roll back and return HTTP 503 with `Retry-After: 2`. No success acknowledgement is emitted for a rolled-back inbound. A later provider retry uses existing event deduplication. |

Business effects remain atomic. This patch **does not remove all transactions
or locks during model inference**. It isolates blocking operations and bounds
lock waits without committing partial appointments, consent changes or replies.
The idle limit deliberately closes a stalled connection; recovery still relies
on the existing durable job retry and idempotent dispatch mechanisms.

No schema migration, model switch or prompt change is required. No lead is
contacted by the tests and no OpenRouter balance is consumed.

## Validation

Offline tests cover sync webhook registration, a slow model-shaped coroutine
running outside the API loop, and rollback/error classification. Existing Sales
regressions cover atomic effects, consent, message dispatch and retry behavior.

Three additional real-PostgreSQL tests are wired into the existing isolated CI
stage (10 PostgreSQL tests total):

1. Transaction limits are reapplied and do not leak to other sessions.
2. A webhook waiting on a locked conversation leaves the API responsive, returns
   503 on timeout, rolls back its event/message/job, and queues exactly once on replay.
3. A slow synthetic job releases a real row lock independently while the API
   accepts the next inbound.

The PostgreSQL tests require `DIALOGUE_POSTGRES_TEST_URL` pointing to a disposable
database ending in `_test`. They create/drop only their private test schema.
The CI runner uses its isolated PostgreSQL container and internal network.
Local validation on PostgreSQL 16.2 passed all **10 tests** using a disposable
TCP server (9.79 seconds). Unix socket creation was unavailable, so TCP was used.
CI repeats these checks against the exact candidate image before deployment. The slow job in that
boundary test is synthetic; it is not a paid end-to-end model quality evaluation.

Final local regression: **3,076 passed, 10 PostgreSQL cases skipped in SQLite**;
those 10 passed separately on PostgreSQL. All 133 source modules were verified
as covered exactly once by the three successful shards. Acceptance: **63 PASS,
0 FAIL, 1 live evaluation NOT_RUN**. No model quality is inferred from these checks.

## After deployment

Run on the server, without sending or replaying production messages:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/version
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/ready
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/sales
```

Check normal sign-in and, using an authorized test lead, a short conversation
with two closely spaced inbound messages. Confirm API health stays responsive,
the durable queue drains and outbound delivery receipts appear. Health alone
does not prove provider delivery or response quality. Provider retry schedules
are external; a 503 does not guarantee an immediate retry.
