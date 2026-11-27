"""Explicit operator-only simulation queue. Runs in SDK container, never live worker.
No HTTP ingress, no global readiness override, no native effect execution.
"""
import argparse
import json
import os
import sys
from contextlib import contextmanager
from uuid import uuid4

from guard import validate, attest
from scoped_policy import (SCOPE, MAX_TURNS, KEY, check_input, check_policy,
                           check_grant, check_scope, require, ScopedDenied)


DDL = (
    """CREATE TABLE IF NOT EXISTS hei06a2_scoped_grant (
      singleton integer PRIMARY KEY CHECK (singleton=1), generation text NOT NULL,
      active boolean NOT NULL, policy_id text NOT NULL, expires_at timestamptz NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS hei06a2_scoped_turn (
      sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE, event_id text PRIMARY KEY,
      generation text NOT NULL, policy_id text NOT NULL, content text NOT NULL,
      status text NOT NULL CHECK (status IN ('pending','running','completed','review','revoked')),
      run_id text, reply_id text, revision integer,
      created_at timestamptz NOT NULL DEFAULT now())""",
)


def sql(conn, statement, **params):
    from sqlalchemy import text
    return conn.execute(text(statement), params)


def scope_session(db):
    from app.modules.hermes_sales_core.contracts import TurnScope
    from app.modules.hermes_sales_core.bp_context import require_scoped_entities
    scope = TurnScope(**SCOPE)
    _, project, lead, conversation = require_scoped_entities(db, scope)
    check_scope(project, lead, conversation)
    return scope


def policy_on_conn(conn):
    from sqlalchemy.orm import Session
    from app.modules.hermes_sales_core.staff_config import snapshot, find_version, normalized
    from app.modules.hermes_sales_core.engine_selection import prompt_policy
    # Hold the publication lock throughout execution, including its separate ORM transaction.
    require(sql(conn, "SELECT id FROM hermes_global_settings WHERE id='global' FOR UPDATE").scalar() == 'global', 'no_policy')
    with Session(bind=conn, join_transaction_mode='rollback_only') as db:
        current = snapshot(db)
        pid = check_policy(current)
        version = find_version(db, pid)
        require(version.is_published and version.published_at and normalized(prompt_policy(version.configuration)) == normalized(current['configuration']), 'invalid_publication')
        return pid


def grant_row(conn):
    return sql(conn, 'SELECT * FROM hei06a2_scoped_grant WHERE singleton=1 FOR UPDATE').mappings().one_or_none()


def seed(engine, SessionLocal):
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    from sqlalchemy.orm import Session
    with engine.begin() as conn:
        attest(conn)
        sql(conn, 'LOCK TABLE hei06a2_guard IN EXCLUSIVE MODE')
        for ddl in DDL: sql(conn, ddl)
        with Session(bind=conn, join_transaction_mode='rollback_only') as db:
            lead = db.get(Lead, SCOPE['lead_id'])
            conv = db.get(SalesConversation, SCOPE['conversation_id'])
            require((lead is None) == (conv is None), 'partial_seed')
            if lead is None:
                db.add(Lead(id=SCOPE['lead_id'],company_id=SCOPE['company_id'],project_id=SCOPE['project_id'],
                    full_name='Synthetic Hermes Buyer',phone='+15550000002',consent_status='granted_simulation',
                    is_opt_out=False,agent_status='paused',is_demo=True,is_test=True))
                db.flush()
                db.add(SalesConversation(id=SCOPE['conversation_id'],company_id=SCOPE['company_id'],
                    project_id=SCOPE['project_id'],lead_id=SCOPE['lead_id'],provider='simulation',channel='simulation',
                    is_paused=False,continuity_json={'lead_id':SCOPE['lead_id'],'project_id':SCOPE['project_id'],'epoch':1}))
                db.flush()
            scope_session(db)
            db.commit()
        # Row exists even before first grant: makes concurrent first grant safe.
        sql(conn, """INSERT INTO hei06a2_scoped_grant(singleton,generation,active,policy_id,expires_at)
             VALUES(1,'ungranted',false,'none',now()) ON CONFLICT(singleton) DO NOTHING""")
    return {'initialized':True}


def grant(conn, SessionLocal):
    row = grant_row(conn)
    require(row is not None and not row['active'], 'revoke_previous_grant_first')
    require(sql(conn,"SELECT count(*) FROM hei06a2_scoped_turn WHERE status IN ('pending','running')").scalar()==0, 'unfinished_queue')
    pid=policy_on_conn(conn)
    with SessionLocal() as db: scope_session(db)
    generation=str(uuid4())
    sql(conn,"UPDATE hei06a2_scoped_grant SET generation=:g,active=true,policy_id=:p,expires_at=now()+interval '60 minutes' WHERE singleton=1",g=generation,p=pid)
    return {'generation':generation,'policy_id':pid,'max_turns':MAX_TURNS,'expires_minutes':60}


def active(conn, SessionLocal):
    row=grant_row(conn)
    pid=policy_on_conn(conn)
    check_grant(row,pid)
    with SessionLocal() as db: scope_session(db)
    return row


def enqueue(conn, SessionLocal, event_id, content):
    check_input(event_id,content)
    row=active(conn,SessionLocal)
    prior=sql(conn,'SELECT * FROM hei06a2_scoped_turn WHERE event_id=:e',e=event_id).mappings().one_or_none()
    if prior:
        require(prior['generation']==row['generation'] and prior['content']==content and prior['policy_id']==row['policy_id'],'event_collision')
        return {'event_id':event_id,'queue_status':prior['status'],'replayed':True}
    require(sql(conn,'SELECT count(*) FROM hei06a2_scoped_turn WHERE generation=:g',g=row['generation']).scalar()<MAX_TURNS,'grant_turn_limit')
    sql(conn,"INSERT INTO hei06a2_scoped_turn(event_id,generation,policy_id,content,status) VALUES(:e,:g,:p,:c,'pending')",e=event_id,g=row['generation'],p=row['policy_id'],c=content)
    return {'event_id':event_id,'queue_status':'pending','replayed':False}


def revoke(conn):
    row=grant_row(conn)
    require(row is not None,'not_initialized')
    sql(conn,'UPDATE hei06a2_scoped_grant SET active=false WHERE singleton=1')
    sql(conn,"UPDATE hei06a2_scoped_turn SET status='revoked' WHERE status='pending'")
    # Acquiring the grant lock proves no worker currently owns the lease.
    # A crash could have committed an in-app receipt; review, NEVER resend.
    sql(conn,"UPDATE hei06a2_scoped_turn SET status='review' WHERE status='running'")
    return {'active':False}


def receipt(SessionLocal, event_id, expected_policy):
    from app.modules.sales_agent.models import AgentRun, SalesMessage
    from app.modules.hermes_sales_core.bp_models import HermesSalesStateEvent
    with SessionLocal() as db:
        scope_session(db)
        run=db.query(AgentRun).filter_by(event_id=event_id,conversation_id=SCOPE['conversation_id'],mode='simulation').one()
        require(run.status=='completed' and run.prompt_configuration_id==expected_policy and run.graph_version=='hermes/hei-01b','run_mismatch')
        inbound=db.query(SalesMessage).filter_by(conversation_id=SCOPE['conversation_id'],channel='simulation',direction='inbound',provider_message_id=event_id).one()
        reply=db.query(SalesMessage).filter_by(conversation_id=SCOPE['conversation_id'],channel='simulation',direction='outbound',provider_message_id='hermes:p08:'+inbound.id).one()
        event=db.query(HermesSalesStateEvent).filter_by(**SCOPE,event_key='hermes:sim:'+inbound.id,event_type='simulation_receipt').one()
        meta=reply.metadata_json or {}; output=run.output_snapshot or {}; result=output.get('metadata') or {}
        require(reply.status=='sent' and meta.get('agent_run_id')==run.id and meta.get('delivery_kind')=='in_app_only' and result.get('message_id')==reply.id and result.get('delivery')=='in_app_only' and result.get('state_revision')==event.revision and output.get('reply')==reply.content and bool(reply.content.strip()),'receipt_mismatch')
        return {'run_id':run.id,'reply_id':reply.id,'revision':event.revision}


@contextmanager
def quiet_model(key):
    # Only this dedicated CLI process receives the secret. Preserve the closed
    # guard's test-only environment outside the invocation; no logs from SDK.
    saved=os.environ.get('OPENROUTER_API_KEY')
    sys.stdout.flush();sys.stderr.flush()
    out,err=os.dup(1),os.dup(2)
    try:
        with open(os.devnull,'wb') as sink:
            os.dup2(sink.fileno(),1);os.dup2(sink.fileno(),2)
            os.environ['OPENROUTER_API_KEY']=key
            yield
    finally:
        os.environ['OPENROUTER_API_KEY']=saved or 'test-only'
        sys.stdout.flush();sys.stderr.flush();os.dup2(out,1);os.dup2(err,2);os.close(out);os.close(err)


def process(conn, engine, SessionLocal, event_id):
    require(isinstance(event_id,str),'invalid_event')
    row=active(conn,SessionLocal)
    job=sql(conn,'SELECT * FROM hei06a2_scoped_turn WHERE event_id=:e',e=event_id).mappings().one_or_none()
    require(job and job['generation']==row['generation'] and job['policy_id']==row['policy_id'],'job_outside_grant')
    if job['status']=='completed':
        got=receipt(SessionLocal,event_id,row['policy_id'])
        require(all(got[k]==job[k] for k in got),'queue_receipt_mismatch')
        return {**got,'event_id':event_id,'queue_status':'completed','replayed':True}
    require(job['status']=='pending','job_not_pending')
    require(sql(conn,"SELECT count(*) FROM hei06a2_scoped_turn WHERE status='running'").scalar()==0,'uncertain_running_job_review')
    require(sql(conn,"SELECT event_id FROM hei06a2_scoped_turn WHERE generation=:g AND status='pending' ORDER BY sequence LIMIT 1",g=row['generation']).scalar()==event_id,'fifo_required')
    key=os.environ.get(KEY,'')
    require(bool(key) and key!='test-only','model_key_missing')
    # This outer transaction holds grant + publication locks. Claim commits on a
    # different connection so a process crash leaves durable uncertain work.
    with engine.begin() as claim:
        require(sql(claim,"UPDATE hei06a2_scoped_turn SET status='running' WHERE event_id=:e AND status='pending'",e=event_id).rowcount==1,'claim_changed')
    try:
        from app.modules.hermes_sales_core.staged_runtime import execute_isolated_turn
        with SessionLocal() as db:
            scope=scope_session(db)
            with quiet_model(key):
                result=execute_isolated_turn(db,scope,event_id=event_id,message=job['content'])
            require(result['delivery']=='in_app_only' and not result['replayed'],'unexpected_runtime_receipt')
        got=receipt(SessionLocal,event_id,row['policy_id'])
        with engine.begin() as done:
            require(sql(done,"UPDATE hei06a2_scoped_turn SET status='completed',run_id=:run_id,reply_id=:reply_id,revision=:revision WHERE event_id=:e AND status='running'",e=event_id,**got).rowcount==1,'completion_changed')
        return {**got,'event_id':event_id,'queue_status':'completed','replayed':False}
    except BaseException:
        with engine.begin() as fail:
            sql(fail,"UPDATE hei06a2_scoped_turn SET status='review' WHERE event_id=:e AND status='running'",e=event_id)
        raise


def status(conn,SessionLocal):
    row=grant_row(conn)
    require(row is not None,'not_initialized')
    from app.modules.sales_agent.models import AgentRun, SalesInboundJob, OutboundMessage, SalesMessage
    from app.modules.sales_crm.models import Meeting
    from app.modules.hermes_sales_core.bp_models import HermesSalesStateEvent
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    with SessionLocal() as db:
        scope_session(db)
        zero={m.__name__:db.query(m).count() for m in (SalesInboundJob,OutboundMessage,Meeting,HermesSalesOperation)}
        require(not any(zero.values()),'unexpected_commercial_effects')
        runs=db.query(AgentRun).filter_by(conversation_id=SCOPE['conversation_id']).count()
        replies=db.query(SalesMessage).filter_by(conversation_id=SCOPE['conversation_id'],channel='simulation',direction='outbound').count()
        events=db.query(HermesSalesStateEvent).filter_by(**SCOPE,event_type='simulation_receipt').count()
    counts=dict(sql(conn,'SELECT status,count(*) FROM hei06a2_scoped_turn GROUP BY status').all())
    return {'active':row['active'],'generation':row['generation'],'policy_id':row['policy_id'],
            'queue_counts':counts,'runs':runs,'replies':replies,'simulation_receipts':events,'commercial_effect_rows':zero}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['init','grant','enqueue','process','revoke','status'])
    parser.add_argument('--event-id')
    a=parser.parse_args()
    report={'schema':'hei06a2b-scoped-simulation/1','action':a.action,'production_readiness':'CLOSED','delivery':'in_app_only','status':'FAIL'}
    try:
        validate()
        require(os.geteuid()==10001 and os.getegid()==10001,'wrong_process_identity')
        from app.db.postgres import engine, SessionLocal
        import app.db.base
        from sqlalchemy.orm import configure_mappers
        from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
        configure_mappers();require(live_hermes_ready() is False,'production_gate_changed')
        if a.action=='init': result=seed(engine,SessionLocal)
        else:
            with engine.begin() as conn:
                attest(conn)
                sql(conn,"SET LOCAL lock_timeout='5s'")
                if a.action=='grant':result=grant(conn,SessionLocal)
                elif a.action=='enqueue':result=enqueue(conn,SessionLocal,a.event_id,sys.stdin.read(4001))
                elif a.action=='process':result=process(conn,engine,SessionLocal,a.event_id)
                elif a.action=='revoke':result=revoke(conn)
                else:result=status(conn,SessionLocal)
        report.update(result);report['status']='PASS'
    except Exception as exc:
        report['exception_type']=type(exc).__name__
        if isinstance(exc,ScopedDenied): report['reason']=str(exc)
        import traceback
        from pathlib import Path
        report['locations']=[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-5:]]
        # Do not print arbitrary exception messages or user/model text.
    print(json.dumps(report,sort_keys=True));return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
