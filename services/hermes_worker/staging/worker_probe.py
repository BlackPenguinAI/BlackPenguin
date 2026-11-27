"""Run the real worker/ORM against a separate SDK service, never real providers.

Each phase uses a new process and the same disposable PostgreSQL. The shell
orchestrator restarts the SDK after preparation and stops it before dispatch.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
from guard import (validate_environment, check_database, assert_scope, inference_count,
                   SCOPE, MESSAGE, POLICY_TOOLS)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def seed(db, engine, report):
    from sqlalchemy import inspect
    from app.db.postgres import Base
    import app.db.base  # noqa: F401
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation, SalesMessage, SalesInboundJob
    from app.modules.hermes_sales_core.staff_models import HermesGlobalVersion, HermesGlobalSettings
    from app.modules.hermes_sales_core.staff_config import baseline
    from app.modules.sales_agent.engine_router import event_scope
    from app.modules.hermes_sales_core.engine_boundary import transition
    # Never create/reset tables against a pre-existing application database.
    report['checkpoint']='fresh_database'
    assert set(inspect(engine).get_table_names()) == {'hei06a_test_guard', 'hei06a_test_inference'}
    assert inference_count(db) == 0
    db.commit()
    report['checkpoint']='orm_create'
    Base.metadata.create_all(engine)
    report['checkpoint']='seed_policy_and_catalog'
    timestamp = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=2)
    policy = {**baseline(), 'enabled': True, 'enabled_tools': list(POLICY_TOOLS)}
    db.add(Company(id='co', name='Test Company', country_code='US', is_active=True)); db.flush()
    db.add(Project(id='project', company_id='co', name='Test Homes', city='Test City', country='US',
                   timezone='America/Lima', is_active=True, is_demo=False)); db.flush()
    db.add_all([
        ProjectProfile(id='profile', project_id='project', final_approved=True, profile_data={}, field_states={}),
        Lead(id='lead', company_id='co', project_id='project', full_name='Test Buyer', phone='+15550000001',
             consent_status='granted', is_opt_out=False, agent_status='active', is_demo=False),
        HermesGlobalVersion(id='version', version=1, configuration=policy, is_published=True, published_at=timestamp),
        HermesGlobalSettings(id='global', last_version=1, published_version_id='version',
                             configuration={**policy, 'active_sales_engine':'hermes'}),
    ]); db.flush()
    for ref, name, price, bathrooms, sort in [('van','Van Buren',325000,1,0), ('oak','Oakwood',340000,2,1)]:
        db.add(ProjectPropertyType(id=ref, project_id='project', name=name, review_status='confirmed',
            bedrooms=3, bathrooms=bathrooms, starting_price=price, currency='USD', available_units=2,
            inventory_updated_at=timestamp, sort_order=sort))
    db.flush()
    conversation = SalesConversation(id='conversation', company_id='co', project_id='project', lead_id='lead',
        provider='telnyx', channel='sms', is_paused=False,
        continuity_json={'lead_id':'lead','project_id':'project','epoch':1,'last_inbound_message_id':'inbound'})
    pin = {**event_scope(conversation, 'telnyx:provider-in'), 'engine':'hermes','policy_version_id':'version'}
    inbound = SalesMessage(id='inbound', conversation_id='conversation', channel='sms', direction='inbound',
        role='user', content=MESSAGE, status='received', provider_message_id='provider-in', created_at=timestamp,
        metadata_json={'lead_id':'lead','project_id':'project','continuity_recorded':True,'sales_engine_pin':pin})
    db.add(conversation); db.flush(); db.add(inbound); db.flush()
    transition(db, conversation, inbound, pin)
    db.add(SalesInboundJob(id='job', conversation_id='conversation', message_id='inbound', status='pending',
                           scheduled_at=timestamp, attempt_number=0))
    db.commit()
    report['policy_fingerprint'] = fingerprint(policy)
    report['checks'].update(fresh_database=True, synthetic_catalog=True, restricted_published_policy=True)


def get_run(db):
    from app.modules.sales_agent.models import AgentRun
    return db.query(AgentRun).filter_by(event_id='telnyx:provider-in').one()


def draft_hash(run):
    envelope = (run.output_snapshot or {}).get('live_draft')
    assert isinstance(envelope, dict) and envelope.get('sha256') and envelope.get('payload')
    from app.modules.hermes_sales_core.live_coordinator import restore_draft
    from app.modules.hermes_sales_core.contracts import TurnScope
    restore_draft(envelope, TurnScope(*SCOPE), 'inbound')
    return envelope['sha256']


def request_checks(run_id, report):
    import httpx
    body = {'job_id':'job','run_id':run_id}
    good = {'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']}
    with httpx.Client(base_url='http://bp-hermes:8080', timeout=4, trust_env=False, follow_redirects=False) as client:
        for _ in range(60):
            try:
                missing = client.post('/internal/prepare', json=body); break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                time.sleep(.5)
        else:
            raise RuntimeError('SDK did not start')
        checks = report['checks']
        checks['missing_auth_401'] = missing.status_code == 401
        checks['wrong_auth_401'] = client.post('/internal/prepare', json=body, headers={'Authorization':'Bearer invalid'}).status_code == 401
        checks['extra_prompt_422'] = client.post('/internal/prepare', json={**body,'prompt':'not allowed'}, headers=good).status_code == 422
        checks['unknown_job_409'] = client.post('/internal/prepare', json={'job_id':'unknown','run_id':run_id}, headers=good).status_code == 409
        checks['wrong_run_409'] = client.post('/internal/prepare', json={**body,'run_id':'unknown'}, headers=good).status_code == 409
        checks['no_openapi_404'] = client.get('/openapi.json').status_code == 404
        assert all(checks.values())


def prepare(db, report):
    from app.modules.sales_agent.live_worker import _claim_inbound_jobs
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from app.modules.hermes_sales_core.live_job import request_sdk_draft
    from app.modules.hermes_sales_core.contracts import TurnScope
    from app.modules.sales_agent.models import OutboundMessage, AgentRun
    db.commit()
    report['checkpoint']='claim_job'
    assert _claim_inbound_jobs(limit=1) == ['job']
    assert _claim_inbound_jobs(limit=1) == []
    assert_scope(db, 'job')
    run = reserve_live_run(db, TurnScope(*SCOPE), inbound_message_id='inbound')
    run_id = run.id; db.commit()
    report['checkpoint']='http_auth_and_binding'
    request_checks(run_id, report)
    assert inference_count(db) == 0 and db.query(AgentRun).count() == 1
    assert db.query(OutboundMessage).count() == 0
    db.commit()
    assert not db.in_transaction()
    report['checkpoint']='private_prepare'
    asyncio.run(request_sdk_draft('job', run_id))
    report['checkpoint']='verify_durable_draft'
    db.expire_all(); run = get_run(db)
    assert run.status == 'running' and run.prompt_configuration_id == 'version'
    assert run.model == 'openai/gpt-4o-mini' and inference_count(db) == 1
    assert db.query(OutboundMessage).count() == 0
    report.update(draft_hash=draft_hash(run), runtime_invocations=1)
    report['checks'].update(worker_claim=True, no_duplicate_claim=True, reserved_policy=True,
                            actual_private_tcp=True, draft_before_dispatch=True, no_provider_outbox=True)
    db.commit()


def replay(db, report):
    from app.modules.hermes_sales_core.live_job import request_sdk_draft
    from app.modules.sales_agent.models import OutboundMessage
    run = get_run(db); run_id = run.id; previous = draft_hash(run)
    assert inference_count(db) == 1 and db.query(OutboundMessage).count() == 0
    db.commit()
    # Wait only for HTTP availability; do not retry an uncertain actual prepare.
    report['checkpoint']='http_auth_and_binding'
    request_checks(run_id, report)
    report['checkpoint']='private_prepare'
    asyncio.run(request_sdk_draft('job', run_id))
    report['checkpoint']='verify_durable_draft'
    db.expire_all(); run = get_run(db)
    assert draft_hash(run) == previous and inference_count(db) == 1
    assert db.query(OutboundMessage).count() == 0
    report.update(draft_hash=previous, runtime_invocations=1)
    report['checks'].update(durable_draft_reused=True, no_second_inference=True, no_provider_outbox=True)
    db.commit()


def finish(db, report):
    from app.modules.sales_agent import live_service
    from app.modules.sales_agent.engine_router import route_live_job
    from app.modules.hermes_sales_core.live_job import process_hermes_inbound_job
    from app.modules.hermes_sales_core.bp_state_store import load
    from app.modules.hermes_sales_core.contracts import TurnScope
    from app.modules.sales_agent.models import AgentRun, SalesMessage, SalesInboundJob, OutboundMessage
    from app.modules.projects.models import SalesAssetShare
    from app.modules.sales_crm.models import Meeting, CalendarConnection
    from focus_grounding import assert_fact_reply
    scope = TurnScope(*SCOPE)
    assert_scope(db, 'job')
    previous = draft_hash(get_run(db)); assert inference_count(db) == 1
    assert db.query(OutboundMessage).count() == 0
    db.commit()
    calls = []
    async def fake_provider(*args, **kwargs):
        # Only synthetic in-memory receipt. No network provider client called.
        calls.append(kwargs['body'])
        return {'sid':'hei06a-simulated-provider-out-'+str(len(calls)), 'status':'sent'}
    async def forbidden_legacy(_job):
        raise AssertionError('No legacy fallback in this fixture')
    async def route():
        return await route_live_job('job', inbound=True, legacy_handler=forbidden_legacy,
                                    hermes_handler=process_hermes_inbound_job)
    with patch.object(live_service, 'send_sms', fake_provider), patch.object(live_service, 'send_message', fake_provider):
        report['checkpoint']='route_and_dispatch'
        assert asyncio.run(route()) is True
        report['checkpoint']='verify_receipt_and_state'
        db.expire_all()
        job = db.get(SalesInboundJob, 'job'); run = get_run(db)
        assert job.status == 'processed' and run.status == 'completed'
        assert len(calls) == 1 and db.query(OutboundMessage).count() == 1
        assert db.query(AgentRun).count() == 1 and inference_count(db) == 1
        outbound = db.query(SalesMessage).filter_by(direction='outbound').one()
        assert outbound.content == calls[0] == (run.output_snapshot or {}).get('reply')
        assert_fact_reply(outbound.content, name='Van Buren', field='bedrooms', value=3)
        assert (db.get(SalesMessage, 'inbound').metadata_json or {}).get('agent_turn_status') == 'answered'
        loaded = load(db, scope)
        assert loaded.revision == 1 and loaded.data['conversation_focus']['property_type_id'] == 'van'
        # Requeue same authenticated synthetic event only, as in HEI-06 fixture.
        report['checkpoint']='completed_event_replay'
        job.status='processing'; db.commit()
        assert asyncio.run(route()) is True
        db.expire_all()
        assert db.get(SalesInboundJob,'job').status == 'processed'
        assert load(db, scope).revision == 1 and inference_count(db) == 1
        assert len(calls) == db.query(OutboundMessage).count() == db.query(AgentRun).count() == 1
        assert db.query(SalesAssetShare).count() == db.query(Meeting).count() == db.query(CalendarConnection).count() == 0
    report.update(draft_hash=previous, runtime_invocations=1, simulated_provider_receipts=1, state_revision=1)
    report['checks'].update(dispatch_from_durable_draft=True, verified_property_fact=True, correct_focus=True,
                            original_policy_pin=True, one_accepted_simulated_receipt=True,
                            replay_no_duplicate=True, no_booking_or_material_effect=True)
    db.commit()


PHASES = {'seed': seed, 'prepare': prepare, 'replay': replay, 'finish': finish}

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--phase', choices=PHASES, required=True)
    p.add_argument('--output', type=Path, required=True); args=p.parse_args()
    report={'schema':'hei06a-private-runtime/1','phase':args.phase,'status':'FAIL','checks':{},
            'production_readiness':'CLOSED','real_message_provider_calls':0,'real_calendar_calls':0}
    try:
        mode=validate_environment();report.update(mode=mode,candidate_commit=os.environ['HEI06A_COMMIT'])
        from app.db.postgres import engine, SessionLocal
        from app.modules.hermes_sales_core import engine_selection
        assert engine_selection.live_hermes_ready() is False
        with engine.connect() as conn:check_database(conn)
        with SessionLocal() as db, patch.object(engine_selection,'live_hermes_ready',return_value=True):
            if args.phase=='seed':seed(db, engine, report)
            else:PHASES[args.phase](db,report)
        assert engine_selection.live_hermes_ready() is False
        report['status']='PASS';report['checkpoint']='complete'
    except Exception as exc:
        # Never serialize raw exception text/traceback or model/provider data.
        report['reason']=type(exc).__name__ if type(exc).__name__ in {
            'AssertionError','PermissionError','RuntimeError','ValueError','ProductionToolError',
            'OperationalError','IntegrityError','HTTPException','ConnectError','ReadTimeout',
            'KeyError','ModuleNotFoundError','ImportError'} else 'other_error'
    finally:
        args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
