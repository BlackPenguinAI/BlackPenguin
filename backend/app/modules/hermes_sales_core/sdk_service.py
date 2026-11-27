"""Private Nous SDK process. Never mount this app on the public BP API.

Start only in the isolated pinned Hermes image, on a private container network
with no published port. It accepts IDs, not prompts or arbitrary tool requests.
It writes only the prepared turn to the existing reserved AgentRun. The API
worker owns every real effect. The private runtime requires a claimed, pinned live event.
"""
from __future__ import annotations
import hmac
import os
import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

app=FastAPI(title='Hermes internal preparation',docs_url=None,redoc_url=None,openapi_url=None)
_PREPARE_LOCK=threading.Lock()


class PrepareRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    job_id: str=Field(min_length=1,max_length=36)
    run_id: str=Field(min_length=1,max_length=36)


def authorize(authorization):
    token=os.environ.get('HERMES_INTERNAL_TOKEN','')
    if len(token)<32:
        raise HTTPException(503,'Private transport is not configured.')
    if not isinstance(authorization,str) or not hmac.compare_digest(authorization.encode(),('Bearer '+token).encode()):
        raise HTTPException(401,'Unauthorized.')


def prepare_reserved(db,request):
    from .production_release import requested, authorize_sdk_job, bind_scope
    if requested():
        scope = authorize_sdk_job(db, request.job_id, request.run_id)
        with bind_scope(scope):
            return _prepare_reserved(db, request)
    return _prepare_reserved(db, request)


def _prepare_reserved(db,request):
    from .engine_selection import HERMES,require_selectable
    from .live_job import lock_job
    from .live_preparation import reserve_live_run,prepare_live_turn
    from .live_coordinator import persist_live_draft,restore_draft
    from .production_tools import ProductionToolError
    require_selectable(HERMES)
    job,scope,conversation,lead,inbound=lock_job(db,request.job_id)
    inbound_id=inbound.id
    run=reserve_live_run(db,scope,inbound_message_id=inbound_id)
    if run.id!=request.run_id or run.status!='running':
        raise ProductionToolError('Request does not identify a reserved live run.')
    previous=(run.output_snapshot or {}).get('live_draft')
    if previous:
        restore_draft(previous,scope,inbound_id);db.commit()
        return {'run_id':request.run_id,'status':'draft_ready'}
    if run.output_snapshot:
        raise ProductionToolError('Unexpected run state.')
    db.commit()
    turn=prepare_live_turn(db,scope,inbound_message_id=inbound_id,run_id=request.run_id)
    # Recheck the claimed job after inference; new inbound / takeover must win.
    job,actual,conversation,lead,inbound=lock_job(db,request.job_id)
    if actual!=scope or inbound.id!=inbound_id:
        raise ProductionToolError('Job was superseded while preparing.')
    persist_live_draft(db,scope,inbound_message_id=inbound_id,run_id=request.run_id,turn=turn)
    db.commit()
    return {'run_id':request.run_id,'status':'draft_ready'}


@app.post('/internal/prepare')
def prepare(request: PrepareRequest, authorization: str | None=Header(default=None)):
    authorize(authorization)
    from .engine_selection import HERMES,require_selectable,EngineUnavailable
    from .production_release import requested, ready
    try:
        if requested():
            if os.getenv('HERMES_RUNTIME_ROLE') != 'sdk' or not ready():
                raise EngineUnavailable('Private SDK is not ready.')
        else:
            require_selectable(HERMES)
    except EngineUnavailable:raise HTTPException(503,'Hermes live preparation is not certified.') from None
    from app.db.postgres import SessionLocal
    from app.modules.sales_agent.concurrency import bounded
    import app.db.base  # noqa: F401 -- ORM registration, no DDL
    # Single isolated SDK process. A second process must not be launched until
    # cross-process job leases are certified. Never queue requests behind an
    # unbounded SDK call; caller will preserve the existing event for review.
    if not _PREPARE_LOCK.acquire(blocking=False):
        raise HTTPException(409,'Hermes preparation is busy.')
    try:
        db=bounded(SessionLocal())
        try:return prepare_reserved(db,request)
        except Exception:
            db.rollback()
            raise HTTPException(409,'Hermes preparation requires review.') from None
        finally:db.close()
    finally:_PREPARE_LOCK.release()


def readiness(authorization: str | None=Header(default=None)):
    authorize(authorization)
    from .production_release import sdk_readiness
    try:
        return sdk_readiness()
    except Exception:
        raise HTTPException(503, 'Private SDK readiness failed.') from None


# Historical offline harnesses retain their original endpoint surface.
from .production_release import requested as _production_requested
if _production_requested():
    app.add_api_route('/internal/readiness', readiness, methods=['GET'])
