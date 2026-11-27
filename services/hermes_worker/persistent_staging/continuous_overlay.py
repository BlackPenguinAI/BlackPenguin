"""Build-time integration for dedicated staging images, never production.
Every upstream file must match the certified Git blob. A missing or duplicate
anchor fails the build. No runtime monkeypatch, import hook or global readiness.
"""
import ast
import hashlib
from pathlib import Path
import sys

CORE='app/modules/hermes_sales_core/'
SALES='app/modules/sales_agent/'
GATEWAY='app/integrations/messaging_gateway.py'

CHANGES={
    CORE+'engine_selection.py': ('26f3d1e46f45f8e945f98d7f8b7209ca4df51e00', [(
        "        raise EngineUnavailable('Hermes live routing is not certified in HEI-01A.')",
        "        from continuous_scope import gate\n        gate()")]),
    SALES+'engine_router.py': ('25820acf3ee622ef25fcd46962299d3b7f63d015', [(
        '    from .models import AgentRun\n    from app.modules.hermes_sales_core.staff_config import engine_status\n    if run is None:\n        run = db.query(AgentRun).filter_by(event_id=event_id).first()\n    return decide(scope=event_scope(conversation, event_id), status=engine_status(db),\n                  pin=pin, run=run)',
        '    from continuous_scope import resolve as scoped_resolve\n    return scoped_resolve(db, conversation, event_id, pin=pin, run=run)')]),
    SALES+'live_worker.py': ('b6ec484d1d809839e9696c053cca47f4b99f76a1', [(
        '    return await route_live_job(job_id, inbound=True, legacy_handler=process_live_inbound_job,\n                                hermes_handler=process_hermes_inbound_job)',
        "    from continuous_scope import bind_job\n    async def deny_legacy(_job_id):\n        raise PermissionError('Legacy execution disabled in scoped staging.')\n    with bind_job(job_id, role='api'):\n        return await route_live_job(job_id, inbound=True, legacy_handler=deny_legacy,\n                                    hermes_handler=process_hermes_inbound_job)"),(
        '        if datetime.utcnow() >= next_calendar_retry:', '        if False:  # Staging has no calendar lane.'),(
        '        if datetime.utcnow() >= next_wait_check:', '        if False:  # Staging has no availability wait lane.'),(
        '            await asyncio.to_thread(_process_operational_outboxes)\n            await asyncio.to_thread(_progress,\'outbox\')',
        "            # No notification outbox processing in this staging image.\n            pass"),(
        '        try:\n            due_ids=await asyncio.to_thread(_claim_due_jobs)',
        "        # Preserve the real continuous inbound polling loop; disable scheduled effects.\n        try:\n            await asyncio.wait_for(stop_event.wait(), timeout=2)\n        except asyncio.TimeoutError:\n            pass\n        continue\n        try:\n            due_ids=await asyncio.to_thread(_claim_due_jobs)")]),
    SALES+'runtime_health.py': ('f1e0a890c8035ba324d18b6497c8f774dc968e5c', [(
        "PHASES=('inbound','followup','calendar','waits','outbox')", "PHASES=('inbound',)  # Only this lane runs in scoped staging."),(
        "'engine':'sales-langgraph/2.0','orchestrator':'graph-observe'", "'engine':'hermes-scoped-staging','orchestrator':'scoped-inbound'")]),
    CORE+'sdk_service.py': ('a61b24af44dc0dd34d72af4d2f03338f16f0b583', [(
        "@app.post('/internal/prepare')\ndef prepare(request: PrepareRequest, authorization: str | None=Header(default=None)):",
        "def _prepare(request: PrepareRequest, authorization: str | None=Header(default=None)):"),(
        "        except Exception:\n            db.rollback()\n            raise HTTPException(409,'Hermes preparation requires review.') from None",
        "        except Exception as exc:\n            from startup_evidence import event\n            event('continuous_sdk','FAIL',exc=exc)\n            db.rollback()\n            raise HTTPException(409,'Hermes preparation requires review.') from None"),]),
    CORE+'live_preparation.py': ('c768501aeb01f54f0f5de756f228011a1b6d1e15', [(
        "    settings=HermesSettings(api_key=os.environ.get('OPENROUTER_API_KEY',''),model=policy.model,",
        "    from continuous_scope import model_key\n    settings=HermesSettings(api_key=model_key(),model=policy.model,")]),
    CORE+'runtime.py': ('026976ab6b1b9545c2dd6cff935facad3158eb4c', [(
        '        with _HERMES_AGENT_LOCK:\n            return self._run_locked(request)',
        '        from continuous_scope import before_inference\n        with _HERMES_AGENT_LOCK:\n            offline = before_inference(self, request)\n            if offline is not None:\n                return offline\n            return self._run_locked(request)')]),
    CORE+'provider_delivery.py': ('c5b83ac33f7b610a2c95e0ac80db5a42388302c9', [(
        '    """Called twice by live_service: before durable enqueue and before provider."""\n',
        '    """Called twice by live_service: before durable enqueue and before provider."""\n    from continuous_scope import authorize_reply\n    authorize_reply(db, conversation, lead, metadata)\n')]),
    CORE+'live_job.py': ('0289bf6005cce157260f0d582885b0da17e14413', [(
        "            schedule_after_reply(db,scope,conversation,lead,inbound,row)",
        "            # Scheduled effects are intentionally unavailable in this staging image.\n            pass"),(
        "    last_id=reply.id;selected=next_native_effect(receipt.state_after,inbound.id)\n",
        "    last_id=reply.id;selected=next_native_effect(receipt.state_after,inbound.id)\n    if selected['preferences'] or selected['kind'] in {'book','cancel','reschedule','material'}:\n        raise ProductionToolError('Native commercial writes blocked in scoped staging.')\n"),(
        '    except Exception:\n        mark_failure(db,job_id);return False',
        "    except Exception as exc:\n        from startup_evidence import event\n        event('continuous_worker','FAIL',exc=exc)\n        mark_failure(db,job_id);return False")]),
    GATEWAY: ('f2ed3e92a0fc320256ab988da853ae9f732821b2', [(
        'async def send_sms(db: Session, *, provider: str, company_id: str, to: str, body: str) -> dict:\n',
        'async def send_sms(db: Session, *, provider: str, company_id: str, to: str, body: str) -> dict:\n    from continuous_scope import simulated_sms\n    return await simulated_sms(provider=provider, company_id=company_id, to=to, body=body)\n'),(
        ') -> dict:\n    if channel == "sms":\n        return await send_sms(db, provider=provider, company_id=company_id, to=to, body=body)',
        ') -> dict:\n    raise PermissionError("Only the scoped SMS transport is available in staging.")\n    if channel == "sms":\n        return await send_sms(db, provider=provider, company_id=company_id, to=to, body=body)')]),
}

SDK_WRAPPER='''

@app.post('/internal/prepare')
def prepare(request: PrepareRequest, authorization: str | None=Header(default=None)):
    authorize(authorization)
    from continuous_scope import bind_job
    try:
        with bind_job(request.job_id, role='sdk', run_id=request.run_id):
            return _prepare(request, authorization)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(409,'Scoped preparation denied.') from None
'''


def git_blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def transform(path,data,*,expected=None):
    sha,edits=CHANGES[path]
    if git_blob(data)!=(expected or sha):raise ValueError('Uncertified blob: '+path)
    source=data.decode('utf-8')
    for old,new in edits:
        if source.count(old)!=1:raise ValueError('Unexpected source anchor: '+path)
        source=source.replace(old,new,1)
    if path==CORE+'sdk_service.py':source+=SDK_WRAPPER
    ast.parse(source,filename=path)
    return source.encode('utf-8')


def main(root):
    # Validate all inputs before changing any. Output stays in the image only.
    updates={name:transform(name,(root/name).read_bytes()) for name in CHANGES}
    for name,data in updates.items():(root/name).write_bytes(data)
    print('Native staging overlay verified:',len(updates),'certified source files')

if __name__=='__main__':main(Path(sys.argv[1]))
