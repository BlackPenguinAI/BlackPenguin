"""Dedicated hosted-CI process composition for the certified live inbound path.
The global readiness flag stays false. The actual worker claim/router/handler,
SDK prepare, dispatcher and receipt functions are reused. Only the readiness
boundary, scoped route decision, offline inference and provider transport are
adapted inside these one-off processes. Never import from the normal API.
"""
import argparse
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
from uuid import uuid4

from guard import validate, attest
from scoped_policy import require, ScopedDenied
from live_scope_policy import (SCOPE, COMPANY_NAME, PROJECT_NAME, LEAD_NAME, PHONE, KEY, MARKER,
    MESSAGES, TOOLS, Capability, validate_case, job_id, inbound_id, provider_id, event_id,
    policy_id, check_capability, check_entities, check_inbound, check_delivery)

CURRENT = ContextVar('hei06a2b2_job_capability', default=None)
DDL = (
    """CREATE TABLE IF NOT EXISTS hei06a2_live_grant (
       singleton integer PRIMARY KEY CHECK(singleton=1), generation text NOT NULL,
       active boolean NOT NULL, policy_id text NOT NULL, expires_at timestamptz NOT NULL,
       company_id text NOT NULL, project_id text NOT NULL, conversation_id text NOT NULL,
       lead_id text NOT NULL, active_job text)""",
    """CREATE TABLE IF NOT EXISTS hei06a2_live_invocation (
       job_id text PRIMARY KEY, generation text NOT NULL, mode text NOT NULL,
       created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS hei06a2_live_send (
       job_id text PRIMARY KEY, generation text NOT NULL, provider_receipt text NOT NULL UNIQUE,
       created_at timestamptz NOT NULL DEFAULT now())""",
)


def sql(db, statement, **params):
    from sqlalchemy import text
    return db.execute(text(statement), params)


def current_grant(db, *, lock=False):
    return sql(db, 'SELECT * FROM hei06a2_live_grant WHERE singleton=1' + (' FOR UPDATE' if lock else '')).mappings().one_or_none()


def published(db):
    from app.modules.hermes_sales_core.staff_config import snapshot, find_version, normalized
    from app.modules.hermes_sales_core.engine_selection import prompt_policy
    s = snapshot(db)
    pid = policy_id(s)
    version = find_version(db, pid)
    require(version.is_published and version.published_at and
            normalized(prompt_policy(version.configuration)) == normalized(s['configuration']), 'live_publication_mismatch')
    return pid


def checked_scope(db):
    from app.modules.hermes_sales_core.bp_context import require_scoped_entities
    from app.modules.hermes_sales_core.contracts import TurnScope
    entities = require_scoped_entities(db, TurnScope(**SCOPE))
    check_entities(*entities)
    return entities


def check_job(db, cap, *, statuses=('processing',), run_id=None):
    from app.modules.sales_agent.models import SalesInboundJob, SalesMessage, AgentRun
    from app.modules.sales_agent.continuity import state
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    attest(db)
    check_capability(current_grant(db), cap, published(db))
    company, project, lead, conversation = checked_scope(db)
    job, inbound = db.get(SalesInboundJob, cap.job_id), db.get(SalesMessage, cap.inbound_id)
    check_inbound(job, inbound, cap, statuses)
    require(state(conversation).get('last_inbound_message_id') == inbound.id, 'live_inbound_superseded')
    if run_id is not None:
        run = db.get(AgentRun, run_id)
        pin = (inbound.metadata_json or {}).get(PIN_KEY)
        require(run is not None and run.conversation_id == conversation.id and run.event_id == event_id(cap.case)
                and run.status == 'running' and run.mode == 'live' and run.graph_version == 'hermes/live/1'
                and run.prompt_configuration_id == cap.policy_id and isinstance(pin, dict)
                and pin == {**event_scope(conversation, event_id(cap.case)), 'engine':'hermes','policy_version_id':cap.policy_id}
                and (run.input_snapshot or {}).get('message_id') == inbound.id
                and (run.input_snapshot or {}).get(PIN_KEY) == pin, 'live_reserved_run_mismatch')
    return job, inbound, conversation


def check_process():
    validate()
    require(os.environ.get('HEI06A2_LIVE_ACCEPTANCE') == MARKER, 'live_process_not_opted_in')
    require(os.geteuid() == 10001 and os.getegid() == 10001, 'live_process_identity')
    from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
    require(live_hermes_ready() is False, 'production_gate_changed')


@contextmanager
def bind(cap):
    require(CURRENT.get() is None, 'nested_live_capability')
    token = CURRENT.set(cap)
    try: yield
    finally: CURRENT.reset(token)


def active_gate(original, SessionLocal):
    """Only current task + fresh DB proof may pass; absent context stays closed."""
    def gate(engine):
        cap = CURRENT.get()
        if engine != 'hermes' or cap is None:
            return original(engine)
        from app.modules.hermes_sales_core.engine_selection import EngineUnavailable
        try:
            check_process()
            with SessionLocal() as db: check_job(db, cap)
            require(cap.case in ('first','second'), 'live_fixture_case_denied')
        except Exception:
            raise EngineUnavailable('Scoped staging authorization denied.') from None
    return gate


@contextmanager
def adapters(SessionLocal, *, worker=False):
    """Only this process's module aliases are composed; no live_hermes_ready override."""
    from app.modules.hermes_sales_core import engine_selection, live_job, live_preparation, live_coordinator, production_tools, provider_delivery, live_receipts
    from app.modules.sales_agent import engine_router
    check_process()
    original = engine_selection.require_selectable
    gate = active_gate(original, SessionLocal)
    def resolve(db, conversation, event, *, pin=None, run=None):
        from app.modules.sales_agent.models import AgentRun
        from app.modules.hermes_sales_core.engine_selection import EngineUnavailable
        cap = CURRENT.get()
        try:
            require(cap is not None, 'live_capability_missing')
            _, _, actual = check_job(db, cap)
            require(cap.case in ('first','second'), 'live_fixture_case_denied')
            require(conversation.id == actual.id and event == event_id(cap.case), 'live_router_scope_mismatch')
            if run is None: run = db.query(AgentRun).filter_by(event_id=event).first()
            result = engine_router._decide(staged=True, scope=engine_router.event_scope(conversation,event),
                       status={'active_sales_engine':'hermes','published_version_id':cap.policy_id}, pin=pin, run=run)
            require(result['policy_version_id'] == cap.policy_id, 'live_router_policy_pin_changed')
            return result
        except (PermissionError, ValueError):
            raise EngineUnavailable('Scoped staging routing denied; no fallback.') from None
    def deny(*args, **kwargs):
        raise PermissionError('Native commercial effect blocked in scoped acceptance.')
    with ExitStack() as stack:
        # The SDK imports require_selectable inside the endpoint and preparation
        # functions. The replacement is task-local in effect, closed otherwise.
        stack.enter_context(patch.object(engine_selection, 'require_selectable', gate))
        for module in (live_job, live_preparation, live_coordinator, production_tools, provider_delivery, live_receipts):
            stack.enter_context(patch.object(module, 'require_selectable', gate))
        if worker:
            from app.modules.hermes_sales_core import live_changes, live_materials
            from app.modules.sales_agent import live_service, live_worker
            stack.enter_context(patch.object(engine_router, 'resolve', resolve))
            # Never run the alternate engine, even if another handler is called.
            async def deny_async(*args, **kwargs): return deny()
            stack.enter_context(patch.object(live_worker, 'process_live_inbound_job', deny_async))
            stack.enter_context(patch.object(production_tools, 'persist_live_preferences', deny))
            stack.enter_context(patch.object(production_tools, 'execute_first_live_booking', deny))
            stack.enter_context(patch.object(live_changes, 'execute_live_change', deny))
            stack.enter_context(patch.object(live_materials, 'issue_live_material_batch', deny))
            stack.enter_context(patch.object(live_materials, 'complete_live_material_batch', deny))
            original_part = provider_delivery.authorize_part
            def scoped_part(db, conversation, lead, metadata, content, key, agent_run_id):
                cap = CURRENT.get()
                require(cap is not None and cap.case != 'revoked', 'live_dispatch_capability_missing')
                _, inbound, actual = check_job(db, cap)
                require(conversation.id == actual.id and lead.id == SCOPE['lead_id'] and
                        metadata.get('hermes_inbound_message_id') == inbound.id and metadata.get('engine') == 'hermes-agent'
                        and metadata.get('hermes_delivery_kind') == 'reply' and not metadata.get('sales_asset_share_ids'),
                        'live_dispatch_outside_reply_lane')
                return original_part(db, conversation, lead, metadata, content, key, agent_run_id)
            stack.enter_context(patch.object(provider_delivery, 'authorize_part', scoped_part))
            async def fake_sms(db, *, provider, company_id, to, body):
                cap = CURRENT.get()
                check_delivery(cap, company_id, provider, to, body)
                check_job(db, cap)
                sid = 'hei06a2b2-simulated-' + cap.job_id
                # Durable count independently of dispatcher transaction. An
                # uncertain or duplicated attempt must not call the stub twice.
                from app.db.postgres import engine
                with engine.begin() as conn:
                    attest(conn)
                    sql(conn, 'INSERT INTO hei06a2_live_send(job_id,generation,provider_receipt) VALUES(:j,:g,:s)',
                        j=cap.job_id,g=cap.generation,s=sid)
                return {'sid':sid,'status':'sent'}
            stack.enter_context(patch.object(live_service, 'send_sms', fake_sms))
            stack.enter_context(patch.object(live_service, 'send_message', deny_async))
        require(engine_selection.live_hermes_ready() is False, 'production_gate_changed')
        yield


def seed(engine, SessionLocal):
    from sqlalchemy.orm import Session
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation, SalesInboundJob, OutboundMessage, SalesFollowUpJob
    from app.modules.sales_crm.models import Meeting
    with engine.begin() as conn:
        attest(conn)
        sql(conn,'LOCK TABLE hei06a2_guard IN EXCLUSIVE MODE')
        for statement in DDL: sql(conn,statement)
        with Session(bind=conn, join_transaction_mode='rollback_only') as db:
            require(current_grant(db) is None, 'live_fixture_already_initialized')
            require(not any(db.query(m).count() for m in (SalesInboundJob, OutboundMessage, SalesFollowUpJob, Meeting)), 'nonempty_commercial_queue')
            pid = published(db)
            require(db.get(Company,SCOPE['company_id']) is None,'live_fixture_already_exists')
            db.add(Company(id=SCOPE['company_id'],name=COMPANY_NAME,country_code='US',is_active=True));db.flush()
            db.add(Project(id=SCOPE['project_id'],company_id=SCOPE['company_id'],name=PROJECT_NAME,city='Test City',country='US',timezone='America/Lima',is_active=True,is_demo=False));db.flush()
            db.add(ProjectProfile(id='stg-live-profile',project_id=SCOPE['project_id'],final_approved=True,profile_data={},field_states={}))
            stamp=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=2)
            for ref,name,price,baths in [('stg-live-van','Van Buren',325000,1),('stg-live-oak','Oakwood',340000,2)]:
                db.add(ProjectPropertyType(id=ref,project_id=SCOPE['project_id'],name=name,review_status='confirmed',bedrooms=3,bathrooms=baths,starting_price=price,currency='USD',available_units=2,inventory_updated_at=stamp,sort_order=baths))
            db.add(Lead(id=SCOPE['lead_id'],company_id=SCOPE['company_id'],project_id=SCOPE['project_id'],full_name=LEAD_NAME,phone=PHONE,consent_status='granted',is_opt_out=False,agent_status='active',is_demo=False,is_test=True));db.flush()
            db.add(SalesConversation(id=SCOPE['conversation_id'],company_id=SCOPE['company_id'],project_id=SCOPE['project_id'],lead_id=SCOPE['lead_id'],provider='telnyx',channel='sms',is_paused=False,continuity_json={'lead_id':SCOPE['lead_id'],'project_id':SCOPE['project_id'],'epoch':1}));db.flush()
            checked_scope(db)
            sql(db,"""INSERT INTO hei06a2_live_grant(singleton,generation,active,policy_id,expires_at,company_id,project_id,conversation_id,lead_id)
                VALUES(1,:generation,true,:policy,now()+interval '30 minutes',:company_id,:project_id,:conversation_id,:lead_id)""",generation=str(uuid4()),policy=pid,**SCOPE)
            db.commit()
    return {'initialized':True,'grant_active':True,'policy_id':pid}


def enqueue(SessionLocal, case):
    from app.modules.sales_agent.models import SalesMessage, SalesInboundJob
    from app.modules.sales_agent.continuity import received
    with SessionLocal() as db:
        attest(db);row=current_grant(db,lock=True)
        require(row is not None, 'live_grant_missing')
        require(row['active'] and row['expires_at'] > datetime.now(timezone.utc) and row['policy_id']==published(db),'live_grant_closed_or_changed')
        cap=Capability(case,row['generation'],row['policy_id'])
        _,_,_,conversation=checked_scope(db)
        prior=db.get(SalesInboundJob,cap.job_id)
        if prior:
            check_inbound(prior,db.get(SalesMessage,cap.inbound_id),cap,('pending','processed','review'))
            return {'job_id':prior.id,'job_status':prior.status,'replayed':True}
        # Only sequential fixtures; never queue a second turn while one is uncertain.
        order=list(MESSAGES)
        for earlier in order[:order.index(case)]:
            prev=db.get(SalesInboundJob,job_id(earlier));require(prev and prev.status=='processed','live_previous_job_unfinished')
        require(not db.query(SalesInboundJob).filter(SalesInboundJob.status.in_(['pending','retry','processing'])).count(),'live_queue_not_empty')
        msg=SalesMessage(id=cap.inbound_id,conversation_id=conversation.id,channel='sms',direction='inbound',role='user',content=MESSAGES[case],status='received',provider_message_id=provider_id(case),metadata_json={'lead_id':SCOPE['lead_id'],'project_id':SCOPE['project_id'],'hei06a2b2_synthetic':MARKER,'hei06a2b2_generation':cap.generation})
        db.add(msg);db.flush();require(received(db,conversation,msg),'live_inbound_awaiting_resume')
        db.add(SalesInboundJob(id=cap.job_id,conversation_id=conversation.id,message_id=msg.id,status='pending',attempt_number=0));db.flush()
        sql(db,'UPDATE hei06a2_live_grant SET active_job=:job WHERE singleton=1',job=cap.job_id)
        db.commit();return {'job_id':cap.job_id,'job_status':'pending','replayed':False}


def receipt(db,case):
    from app.modules.sales_agent.models import SalesInboundJob,AgentRun,SalesMessage,OutboundMessage
    from app.modules.hermes_sales_core.bp_state_store import load
    from app.modules.hermes_sales_core.contracts import TurnScope
    from app.modules.hermes_sales_core.bp_models import HermesSalesStateEvent
    from app.modules.hermes_sales_core.production_tools import _verify_provider_receipt
    job=db.get(SalesInboundJob,job_id(case));msg=db.get(SalesMessage,inbound_id(case))
    require(job is not None and job.status=='processed' and msg is not None,'live_job_not_processed')
    run=db.query(AgentRun).filter_by(event_id=event_id(case)).one()
    require(run.conversation_id==SCOPE['conversation_id'] and run.graph_version=='hermes/live/1' and run.mode=='live' and run.status=='completed','live_run_not_completed')
    pin=(msg.metadata_json or {}).get('sales_engine_pin') or {}
    require(pin.get('engine')=='hermes' and pin.get('policy_version_id')==run.prompt_configuration_id,'live_pin_mismatch')
    out=db.query(OutboundMessage).filter_by(agent_run_id=run.id).one()
    reply=db.query(SalesMessage).filter_by(conversation_id=SCOPE['conversation_id'],direction='outbound',provider_message_id=out.provider_message_id).one()
    _verify_provider_receipt(db,reply,TurnScope(**SCOPE),'sms')
    require(out.provider_message_id=='hei06a2b2-simulated-'+job.id and out.recipient==PHONE and out.content==reply.content
            and (reply.metadata_json or {}).get('hermes_inbound_message_id')==msg.id
            and (msg.metadata_json or {}).get('handled_by_message_id')==reply.id
            and (run.output_snapshot or {}).get('reply')==reply.content,'live_receipt_binding_mismatch')
    loaded=load(db,TurnScope(**SCOPE))
    require((loaded.data.get('conversation_focus') or {}).get('property_type_id')=='stg-live-van','live_focus_mismatch')
    require(db.query(HermesSalesStateEvent).filter_by(**SCOPE,event_key='hermes:live:'+msg.id,event_type='outbound_choice_receipt').count()==1,'live_state_event_missing')
    # Check the known synthetic fact, not an exact model wording.
    fact = r'\b(?:3|three)\s*[- ]?\s*bedrooms?\b' if case=='first' else r'\b(?:1|one|a single|a)\s*[- ]?\s*bathrooms?\b'
    require('van buren' in reply.content.casefold() and bool(re.search(fact,reply.content,re.I)),'live_verified_fact_missing')
    inv=sql(db,'SELECT count(*) FROM hei06a2_live_invocation WHERE job_id=:j',j=job.id).scalar()
    sends=sql(db,'SELECT count(*) FROM hei06a2_live_send WHERE job_id=:j',j=job.id).scalar()
    require(inv==sends==1,'live_duplicate_or_missing_invocation')
    return {'job_id':job.id,'run_id':run.id,'reply_id':reply.id,'revision':loaded.revision,'invocations':inv,'simulated_sends':sends,'policy_id':run.prompt_configuration_id}


def requeue(SessionLocal,case):
    from app.modules.sales_agent.models import SalesInboundJob
    require(case=='first','live_replay_only_first_fixture')
    with SessionLocal() as db:
        attest(db);row=current_grant(db,lock=True)
        cap=Capability(case,row['generation'],row['policy_id'])
        check_job(db,cap,statuses=('processed',));prior=receipt(db,case)
        job=db.get(SalesInboundJob,cap.job_id);job.status='pending';job.processed_at=None;job.claimed_at=None
        db.commit();return prior


def revoke(SessionLocal):
    with SessionLocal() as db:
        attest(db);row=current_grant(db,lock=True);require(row is not None,'live_grant_missing')
        sql(db,'UPDATE hei06a2_live_grant SET active=false WHERE singleton=1');db.commit()
    return {'grant_active':False}


def request_checks(cap):
    import httpx,time
    body={'job_id':cap.job_id,'run_id':'not-a-reserved-run'}
    auth={'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']}
    with httpx.Client(base_url='http://bp-hermes:8080',timeout=5,trust_env=False,follow_redirects=False) as client:
        for _ in range(60):
            try: r=client.post('/internal/prepare',json=body);break
            except (httpx.ConnectError,httpx.ConnectTimeout):time.sleep(.5)
        else:raise RuntimeError('private SDK not available')
        require(r.status_code==401,'live_sdk_missing_auth_not_denied')
        require(client.post('/internal/prepare',json=body,headers={'Authorization':'Bearer invalid'}).status_code==401,'live_sdk_wrong_auth_not_denied')
        require(client.post('/internal/prepare',json={**body,'prompt':'arbitrary'},headers=auth).status_code==422,'live_sdk_extra_fields_not_denied')
        require(client.post('/internal/prepare',json=body,headers=auth).status_code==409,'live_sdk_unreserved_run_not_denied')
        require(client.post('/internal/prepare',json={'job_id':'outside-scope','run_id':'outside-scope'},headers=auth).status_code==409,'live_sdk_foreign_job_not_denied')
        require(client.get('/openapi.json').status_code==404,'live_sdk_openapi_exposed')
    return 6


def safe_failure(exc):
    import traceback
    from startup_evidence import IDENT, SAFE_FILE
    name=type(exc).__name__
    return {'exception_type':name if IDENT.fullmatch(name) else 'UnknownError',
            'locations':[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__) if SAFE_FILE.fullmatch(Path(f.filename).name)][-8:]}


def run_worker(engine,SessionLocal,case,report):
    from app.modules.sales_agent import live_worker
    from app.modules.hermes_sales_core import live_job
    from app.modules.sales_agent.models import SalesInboundJob, AgentRun, OutboundMessage
    # Claim transaction and route are the existing worker code. This is an
    # explicit one-shot inbound lane, not the continuously scanning API worker.
    with engine.begin() as lease:
        attest(lease)
        row=current_grant(lease,lock=True);require(row is not None,'live_grant_missing')
        require(sql(lease,"SELECT id FROM hermes_global_settings WHERE id='global' FOR UPDATE").scalar()=='global','live_policy_missing')
        cap=Capability(case,row['generation'],row['policy_id'])
        require(row['active_job']==cap.job_id,'live_job_not_leased')
        report['checkpoint']='claim_existing_worker'
        with SessionLocal() as db:
            require(db.query(SalesInboundJob).filter(SalesInboundJob.status.in_(['pending','retry','processing'])).count()==1,'live_unexpected_pending_work')
        require(live_worker._claim_inbound_jobs(limit=1)==[cap.job_id],'live_worker_claim_mismatch')
        require(live_worker._claim_inbound_jobs(limit=1)==[],'live_duplicate_claim')
        report['checkpoint']='private_sdk_denials'
        report['http_negative_checks']=request_checks(cap)
        report['checkpoint']='route_existing_worker'
        original_run=live_job.run_job
        async def measured_job(*args,**kwargs):
            try:return await original_run(*args,**kwargs)
            except Exception as exc:
                report['worker_failure']=safe_failure(exc)
                raise
        with adapters(SessionLocal,worker=True),bind(cap),patch.object(live_job,'run_job',measured_job):
            routed=live_worker._isolated_job(live_worker._routed_inbound_job,cap.job_id)
        report['checkpoint']='verify_job_and_receipt'
        with SessionLocal() as db:
            if case=='revoked':
                job=db.get(SalesInboundJob,cap.job_id)
                require(routed is False and job.status=='review' and job.error_code=='HERMES_NOT_READY','live_revoked_route_not_denied')
                require(db.query(AgentRun).filter_by(event_id=event_id(case)).count()==0 and sql(db,'SELECT count(*) FROM hei06a2_live_invocation WHERE job_id=:j',j=cap.job_id).scalar()==0 and sql(db,'SELECT count(*) FROM hei06a2_live_send WHERE job_id=:j',j=cap.job_id).scalar()==0,'live_revoked_effect')
                return {'revoked_job_review':True,'job_status':'review'}
            if routed is not True:
                job=db.get(SalesInboundJob,cap.job_id)
                report['job_status']=job.status if job else 'missing'
                report['job_error_code']=job.error_code if job and job.error_code in {'HERMES_NOT_READY','ENGINE_SELECTION_REVIEW','HERMES_RECONCILIATION_REQUIRED','HERMES_PROVIDER_PENDING'} else 'other'
                report['invocations']=sql(db,'SELECT count(*) FROM hei06a2_live_invocation WHERE job_id=:j',j=cap.job_id).scalar()
                report['simulated_sends']=sql(db,'SELECT count(*) FROM hei06a2_live_send WHERE job_id=:j',j=cap.job_id).scalar()
                raise ScopedDenied('live_worker_did_not_finish')
            return receipt(db,case)


def status(SessionLocal):
    from app.modules.sales_agent.models import SalesInboundJob, AgentRun, OutboundMessage, SalesMessage, SalesFollowUpJob
    from app.modules.sales_crm.models import Meeting, CalendarConnection
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    from app.modules.projects.models import SalesAssetShare
    from app.modules.hermes_sales_core.bp_state_store import load
    from app.modules.hermes_sales_core.contracts import TurnScope
    with SessionLocal() as db:
        attest(db);row=current_grant(db);checked_scope(db)
        ids=SCOPE['conversation_id']
        counts={m.__name__:db.query(m).filter_by(conversation_id=ids).count() for m in (AgentRun,OutboundMessage,SalesInboundJob)}
        counts['replies']=db.query(SalesMessage).filter_by(conversation_id=ids,direction='outbound').count()
        counts['invocations']=sql(db,'SELECT count(*) FROM hei06a2_live_invocation').scalar()
        counts['simulated_sends']=sql(db,'SELECT count(*) FROM hei06a2_live_send').scalar()
        zero={m.__name__:db.query(m).count() for m in (Meeting,CalendarConnection,HermesSalesOperation,SalesAssetShare,SalesFollowUpJob)}
        require(not any(zero.values()),'live_unexpected_commercial_effect')
        require(not row['active'],'live_grant_not_revoked')
        require(db.query(SalesInboundJob).filter(SalesInboundJob.status.in_(['pending','retry','processing'])).count()==0,'live_pending_work_after_revocation')
        require(counts=={'AgentRun':2,'OutboundMessage':2,'SalesInboundJob':3,'replies':2,'invocations':2,'simulated_sends':2},'live_final_counts_mismatch')
        revision=load(db,TurnScope(**SCOPE)).revision;require(revision==2,'live_final_revision_mismatch')
        return {'counts':counts,'revision':revision,'commercial_effect_rows':zero,'grant_active':False}


@contextmanager
def quiet_output():
    sys.stdout.flush();sys.stderr.flush();out,err=os.dup(1),os.dup(2)
    try:
        with open(os.devnull,'wb') as sink:
            os.dup2(sink.fileno(),1);os.dup2(sink.fileno(),2)
            yield
    finally:
        sys.stdout.flush();sys.stderr.flush();os.dup2(out,1);os.dup2(err,2);os.close(out);os.close(err)


def serve_sdk(engine,SessionLocal,model):
    from fastapi import FastAPI,Header,HTTPException
    from app.modules.hermes_sales_core import sdk_service
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    import uvicorn
    key=os.environ.get(KEY,'');require(bool(key and key!='test-only') if model else not key,'live_model_key_mode_mismatch')
    original=HermesSalesRuntime.process_turn
    original_prepare=sdk_service.prepare_reserved
    def measure(runtime,request):
        cap=CURRENT.get();require(cap is not None and cap.case in ('first','second'),'live_sdk_missing_capability')
        require(request.scope.__dict__==SCOPE and request.message==MESSAGES[cap.case] and request.channel=='sms','live_sdk_request_mismatch')
        require(runtime._enabled_tools==TOOLS,'live_sdk_tools_mismatch')
        with SessionLocal() as db:check_job(db,cap)
        with engine.begin() as c:
            attest(c);sql(c,'INSERT INTO hei06a2_live_invocation(job_id,generation,mode) VALUES(:j,:g,:m)',j=cap.job_id,g=cap.generation,m='model' if model else 'offline')
        if model:
            saved=runtime._settings;runtime._settings=replace(saved,api_key=key)
            try:
                with quiet_output():return original(runtime,request)
            finally:runtime._settings=saved
        prop=request.verified_context.get('focused_property') or {}
        require(prop.get('display_name')=='Van Buren' and prop.get('bedrooms')==3 and prop.get('bathrooms')==1,'live_offline_verified_context_missing')
        return TurnResult('Van Buren has 3 bedrooms.' if cap.case=='first' else 'Van Buren has 1 bathroom.',[],[])
    def diagnostic_prepare(db,request):
        try:return original_prepare(db,request)
        except Exception as exc:
            print('HEI06A2_LIVE_EVENT '+json.dumps({'phase':'scoped_live_sdk_prepare','status':'FAIL',**safe_failure(exc)},sort_keys=True),flush=True)
            raise
    app=FastAPI(title='Scoped CI private preparation',docs_url=None,redoc_url=None,openapi_url=None)
    @app.post('/internal/prepare')
    def endpoint(request:sdk_service.PrepareRequest, authorization:str|None=Header(default=None)):
        sdk_service.authorize(authorization)
        try:
            case=next(c for c in MESSAGES if job_id(c)==request.job_id)
            with SessionLocal() as db:
                row=current_grant(db);require(row is not None,'live_grant_missing')
                cap=Capability(case,row['generation'],row['policy_id']);check_job(db,cap,run_id=request.run_id)
        except Exception:raise HTTPException(409,'Scoped preparation denied.') from None
        with bind(cap):return sdk_service.prepare(request,authorization)
    with adapters(SessionLocal),patch.object(HermesSalesRuntime,'process_turn',measure),patch.object(sdk_service,'prepare_reserved',diagnostic_prepare):
        uvicorn.run(app,host='0.0.0.0',port=8080,workers=1,proxy_headers=False,access_log=False,log_level='critical',lifespan='off')


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','enqueue','run','requeue','revoke','status','sdk']);p.add_argument('--case',choices=list(MESSAGES));p.add_argument('--model',action='store_true');a=p.parse_args()
    report={'schema':'hei06a2b2-live-worker/1','action':a.action,'status':'FAIL','checkpoint':'environment','production_readiness':'CLOSED','real_provider_acceptance':'NOT_RUN'}
    try:
        check_process();require((a.action in ('enqueue','run','requeue'))==bool(a.case),'live_case_required')
        require(not a.model or a.action=='sdk','live_model_only_sdk')
        require(a.action=='sdk' or not os.environ.get(KEY),'live_key_in_worker')
        from app.db.postgres import engine,SessionLocal
        import app.db.base
        from sqlalchemy.orm import configure_mappers
        with engine.connect() as c:attest(c)
        configure_mappers()
        report['checkpoint']=a.action
        if a.action=='sdk':serve_sdk(engine,SessionLocal,a.model);return 0
        if a.action=='init':result=seed(engine,SessionLocal)
        elif a.action=='enqueue':result=enqueue(SessionLocal,a.case)
        elif a.action=='run':result=run_worker(engine,SessionLocal,a.case,report)
        elif a.action=='requeue':result=requeue(SessionLocal,a.case)
        elif a.action=='revoke':result=revoke(SessionLocal)
        else:result=status(SessionLocal)
        report.update(result);report.update(status='PASS',checkpoint='complete')
    except Exception as exc:
        import traceback
        report['exception_type']=type(exc).__name__
        if isinstance(exc,ScopedDenied):report['reason']=str(exc)
        report['locations']=[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-6:]]
    print(json.dumps(report,sort_keys=True));return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
