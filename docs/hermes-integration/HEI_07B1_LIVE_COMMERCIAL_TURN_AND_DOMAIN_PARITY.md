# HEI-07B.1 — Live Commercial Turn & Domain Parity

Base: `cc25fff5cb6c2c50377d73c51a4db73415b28d94` (deployed candidate #485). Upload Ready differential; replace the complete files at their paths. No migrations, new secrets, new staging workflows, or onboarding changes. No published policy/prompt changes.

## Evidence and hypothesis

The Cedar WhatsApp conversation had five delivered responses but only two completed runs. Three proposed replies and provider groups validate retrospectively. All three had expected state revision 1, and the final revision was 2. The original exception was swallowed by the old worker; its exact cause cannot be recovered from these logs alone.

A concrete defect is that the FIFO worker retries known pending receipts after 30 seconds, but `reserve_live_run` previously required the inbound to remain the latest. The next inbound arrived ~16 seconds after each of the three responses. The next inbound may therefore invalidate an already-sent reply's receipt retry. This is a reproducible candidate mechanism, not a proven reconstruction of the original exception. A new stage/exception-class/location diagnostic is added for further evidence.

The SDK container has its own `/tmp/bp-hermes-uploads` and does not mount the API's encrypted production files. `live_preparation._verified_material` previously ran `_material_batch`, which checks physical storage, in the SDK. Both Cleveland resources were approved and verified in the API. The new discovery lane checks current tenant/project/property/channel and approval/coverage metadata only. It does not claim that the file is readable or issue any URL. The existing API `issue_live_material_batch` still calls `_material_batch`, validates file integrity/encryption and issues the scoped share. The final provider authorization, share validation, idempotency and completion contracts are unchanged. A storage failure during actual issuance is exposed as a review at `material_storage_verification`, rather than disappearing during discovery. The provisional reply makes no claim of actual sharing. Buyer-facing recovery from failed issuance remains an improvement, not implemented here.

## Changes

- `live_preparation.py`: receipt-only reservation of an existing immutable planned run; no creation of a new run on this lane. Normal inference requires the latest authenticated inbound. Exact event pin, current policy, epoch, consent, project approval and tenant checks stay in place. The receipt-only option is used by the API worker, not by the SDK preparation endpoint.
- `live_job.py`: a known planned reply on retry is reconciled only against its original durable provider group. It cannot trigger another send if the group is absent. New unsent model replies are rejected when overtaken by another inbound. Accepted prior replies may consolidate while a later buyer message waits in FIFO, provided the existing receipt, revision and supersession checks pass. Pending receipt polling uses 3 seconds for the first three attempts, then 30 seconds, with the original 10-attempt cap. No provider network replay is introduced. Failures record safe checkpoint, exception class, source filename/line and optional SQLSTATE on the inbound metadata and in a warning log (no raw exception text, payloads, credentials or bearer links).
- `live_domain_parity.py`: approved material candidate discovery without SDK filesystem access. Contextual evidence for a buyer's first explicit bedroom preference and acceptance of a specifically offered no-match alternative. The latter needs a previous scoped accepted assistant message and a matching zero-result prior search. Re-derive that evidence before projecting the state to the existing CRM writer. Do not overwrite staff-verified fields. Existing direct-preference pathway remains available. These are bounded evidence contracts for the observed phrases, not generic intent classification or a second LLM. No broad arbitrary `update_lead_profile` permission is added; purchase timeline and other unhandled CRM fields remain outside this candidate.
- `test_bp_hei07b1_live_domain_parity.py`: tests the observed declarations, temporary searches, late provider receipt with newer inbound, receipt-only no creation, metadata-only material discovery and native file validation, and redacted failure evidence. The repository's existing real ORM fixture uses synthetic data and fake provider methods. The complete suite is intended to run in ordinary deploy CI.

## Deployment

1. Pause manual testing and ensure there are no pending/retry/processing Hermes jobs for the test conversation. Do not replay or edit old `review` jobs. Preserve the existing diagnostics.
2. The existing deploy helper expressly requires the selected Sales Agent to be LangGraph before replacing the API/SDK containers. Temporarily select LangGraph from Sales Agent ONLY for this maintenance window, and do not send test messages during it. No automatic engine switch is introduced. After a successful deploy, select Hermes again. No need to re-publish the existing policy.
3. Upload the five files (including this document) to `main` using GitHub Upload files with the same paths. Commit: `fix(hermes): reconcile live receipts and restore commercial domain parity`.
4. Check the normal DigitalOcean deploy and isolated evaluation. No new manual staging workflow.
5. After `hermes_private_transport=ready` and `Private SDK ready`, explicitly select Hermes. Start a clean test conversation through the existing CRM; the three older review runs are not replayed or repaired automatically by this candidate. Keep the original export for comparison.

## Manual acceptance — Cedar

Send one message at a time. Wait for the complete response (including the link on a material turn). Adapt an ordinal to the actual menu displayed: choose Cleveland, not blindly option 2 if order changes.

1. `I’m looking for a 2-bedroom house` — no exact match; preference retained as 2 bedrooms.
2. If the agent specifically offers 3 bedrooms: `Yes, 3 bedrooms it’s ok` — record accepted preference as 3 and return verified alternatives.
3. `Option 2` (only if Cleveland is option 2) — delivered menu selects Cleveland in persisted focus.
4. `Show me photos of this property` — approved Cleveland gallery link, not fabricated URL. Open on phone.
5. `Brochure it’s ok` — approved Cleveland PDF link. Open on phone. PDF is tagged brochure, not floor_plan.
6. Ask `What is its total area?` — 1,884 ft² according to the approved Cedar catalog, without repeating the property name.
7. `Show me other 4-bedroom houses` — temporary search must not silently replace the accepted primary preference.

Expected: latest runs `completed` and jobs `processed`; CRM bedrooms and Hermes focus recorded; exact provider receipt IDs and no duplicate outbox entries. Material requests may produce two messages (provisional and actual authorized link), as in the existing delivery protocol. SMS, real Calendar and broad profile updates need separate acceptance, not claimed by this candidate.

## If a turn fails

Use the current test conversation ID, not the original diagnostic conversation ID, unless testing that exact conversation. From SSH run the following read-only query. It prints only scoped IDs, status and sanitized failure evidence, not message text, token-bearing links, telephone numbers or credentials:

```bash
docker exec -i -w /app bp_api_prod python - <<'PY'
import json
from sqlalchemy import text
import app.db.base
from app.db.postgres import SessionLocal
from app.modules.sales_agent.models import SalesMessage, SalesInboundJob, AgentRun
from app.modules.hermes_sales_core.bp_models import HermesSalesState
CID = 'REPLACE_WITH_CURRENT_TEST_CONVERSATION_ID'
db = SessionLocal()
try:
    db.execute(text('SET TRANSACTION READ ONLY'))
    for j in db.query(SalesInboundJob).filter_by(conversation_id=CID).order_by(SalesInboundJob.created_at.desc()).limit(15):
        m = db.get(SalesMessage, j.message_id)
        print('JOB', json.dumps({'id':j.id,'status':j.status,'error_code':j.error_code,'diagnostic':(m.metadata_json or {}).get('hermes_failure_diagnostic') if m else None},default=str))
    for r in db.query(AgentRun).filter_by(conversation_id=CID).order_by(AgentRun.started_at.desc()).limit(15):
        o = r.output_snapshot or {}; d=(o.get('live_draft') or {}).get('payload') or {}
        print('RUN', json.dumps({'id':r.id,'engine':r.graph_version,'status':r.status,'expected_revision':d.get('expected_revision'),'state_revision':(o.get('metadata') or {}).get('state_revision'),'tools':o.get('tool_observations') or d.get('observations'),'profile_fields':(o.get('native_live_profile') or {}).get('updated_fields')},default=str))
    for s in db.query(HermesSalesState).filter_by(conversation_id=CID):
        v=s.state_json or {}
        print('STATE',json.dumps({'revision':s.revision,'focus':v.get('conversation_focus'),'preferences':v.get('search_preferences')},default=str))
finally:
    db.rollback();db.close()
PY
```

## Validation limits

The two original modified files were matched to their GitHub blob hashes before edits (`live_preparation.py` c768501aeb01f54f0f5de756f228011a1b6d1e15; `live_job.py` 0289bf6005cce157260f0d582885b0da17e14413). Python compilation and isolated contextual-evidence assertions passed locally. Full repository, Docker, real PostgreSQL worker, Telnyx and Google Calendar were not run locally. The new ORM regression tests have been authored, not certified. Old staging-specific fixtures may enforce historical baselines; do not use them as substitute for production acceptance.
