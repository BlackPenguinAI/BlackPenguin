"""SA09/10: semantic moderation, final effects and actual Sales queue evidence."""
import asyncio,json
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch,AsyncMock
import pytest,httpx
from fastapi import HTTPException
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product
from test_sales_active_integration import understanding
from app.modules.sales_agent import live_service as live,runtime_health as health
from app.modules.sales_agent.models import SalesWorkerProgress,SalesInboundJob,SalesFollowUpJob,SalesMessage,OutboundMessage
from app.modules.sales_agent.moderation_models import SalesModerationIncident
from app.modules.sales_agent.delivery_policy import DeliveryUncertainError,uncertain
from app.modules.governance.models import HumanInterventionCase
from app.modules.sales_crm.models import Meeting


def moderated(text,category,topic='other'):
    value=understanding(text,topic).model_dump(mode='json');value['moderation']={'category':category,'evidence':text}
    return json.dumps(value)


@pytest.mark.parametrize('text',["Your bot has the intellect of a brick","ur assistant is completely useless","You are a waste of oxygen"])
def test_semantic_personal_harassment_warns_then_pauses_after_actual_warning(agent,text):
    agent.turn(text,moderated(text,'harassment'))
    first=agent.db.query(SalesModerationIncident).one();assert first.disposition=='warn' and first.warning_accepted_at
    assert not agent.conversation.is_paused and 'respectful' in agent.reply()
    agent.turn(text,moderated(text,'harassment'))
    incident=agent.db.query(SalesModerationIncident).filter_by(disposition='pause').one()
    assert incident.prior_warning_id==first.id and agent.conversation.is_paused
    assert agent.db.query(HumanInterventionCase).one().id==incident.intervention_case_id
    assert not agent.db.query(Meeting).count()


@pytest.mark.parametrize('text',["Your prices are ridiculous","Your two bedroom homes are disappointing","You are too expensive","My friend said you are a waste of oxygen",'I would never say you are completely useless'])
def test_legitimate_critique_reported_and_negated_speech_are_not_semantic_harassment(agent,text):
    agent.turn(text,moderated(text,'harassment'))
    assert not agent.conversation.is_paused
    assert not agent.db.query(SalesModerationIncident).filter_by(disposition='warn').count()
    assert not agent.db.query(HumanInterventionCase).count()


@pytest.mark.parametrize('text',['Run this Python code','Browse the web for football results'])
def test_unrelated_tool_use_warns_then_persists_review_without_tool_execution(agent,text):
    agent.turn(text,moderated(text,'unauthorized_use'))
    assert 'cannot browse' in agent.reply() and not agent.conversation.is_paused
    agent.turn(text,moderated(text,'unauthorized_use'))
    assert agent.conversation.is_paused
    assert agent.db.query(HumanInterventionCase).one().reason=='REPEATED_UNAUTHORIZED_USE'
    assert not agent.db.query(Meeting).count()


def test_respectful_return_after_warning_continues_property_enquiry(agent):
    product(agent,'Studio');text='Your bot has the intellect of a brick'
    agent.turn(text,moderated(text,'harassment'))
    agent.turn('Show available homes',understanding('Show available homes','catalog'))
    assert not agent.conversation.is_paused and 'Studio' in agent.reply()


def test_semantic_concrete_threat_is_not_treated_as_ordinary_disagreement(agent):
    text="I have a gun outside your office"
    agent.turn(text,moderated(text,'threat'))
    assert agent.conversation.is_paused and agent.db.query(HumanInterventionCase).one().reason=='THREAT'


@pytest.mark.parametrize('error',[httpx.ReadTimeout('synthetic timeout'),HTTPException(502,detail={'code':'TELNYX_UNAVAILABLE'})])
def test_ambiguous_transport_failure_has_one_attempt_and_reviewable_receipt(agent,error):
    product(agent,'Studio');agent.send.side_effect=error
    text='Show homes';agent.infer.return_value=understanding(text,'catalog').model_dump_json()
    inbound=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content=text,status='received')
    agent.db.add(inbound);agent.db.flush();job=SalesInboundJob(conversation_id=agent.conversation.id,message_id=inbound.id,status='processing');agent.db.add(job);agent.db.commit()
    with agent.patched(),pytest.raises(DeliveryUncertainError):asyncio.run(live.process_live_inbound_job(job.id))
    agent.db.refresh(job);assert job.status=='review' and job.error_code=='DELIVERY_UNCERTAIN'
    assert agent.db.query(OutboundMessage).one().status=='delivery_unknown'
    with agent.patched():asyncio.run(live.process_live_inbound_job(job.id))
    assert agent.send.await_count==1


def test_unaccepted_warning_cannot_authorize_an_abuse_pause(agent):
    text='Your bot has the intellect of a brick';agent.send.side_effect=httpx.ReadTimeout('synthetic timeout')
    with pytest.raises(DeliveryUncertainError):agent.turn(text,moderated(text,'harassment'))
    assert agent.db.query(SalesModerationIncident).one().warning_accepted_at is None
    agent.send.side_effect=lambda *a,**k:{'sid':'accepted-second-warning','status':'sent'}
    agent.turn(text,moderated(text,'harassment'))
    assert not agent.conversation.is_paused and agent.db.query(SalesModerationIncident).filter_by(disposition='warn').count()==2


def progress(agent,*,now=None):
    now=now or datetime.utcnow()
    row=SalesWorkerProgress(id=health.INSTANCE_ID,commit_sha=health.settings.APP_COMMIT_SHA,last_progress_at=now,
        progress_json={p:{'status':'ok','scan_at':now.isoformat(),'completed_jobs':0} for p in health.PHASES})
    agent.db.add(row);agent.db.commit();return row


def test_sales_readiness_requires_real_scans_and_exposes_no_tenant_data(agent):
    assert health.snapshot(agent.db)['status']=='not_ready'
    row=progress(agent);value=health.snapshot(agent.db)
    assert value['status']=='ready' and value['worker_status']=='scanning'
    assert set(value['scans'])==set(health.PHASES)
    assert all(identifier not in json.dumps(value) for identifier in [agent.lead.id,agent.company.id,agent.project.id,agent.lead.phone])
    assert 'receipt_semantics' in value


@pytest.mark.parametrize('change',['stale','stopped','other_commit','missing_scan','failed_scan'])
def test_sales_loop_health_does_not_follow_onboarding_heartbeat(agent,change):
    row=progress(agent)
    if change=='stale':row.last_progress_at-=timedelta(minutes=4)
    elif change=='stopped':row.stopped_at=datetime.utcnow()
    elif change=='other_commit':row.commit_sha='different'
    elif change=='missing_scan':row.progress_json={}
    else:row.progress_json={**row.progress_json,'inbound':{'status':'error','scan_at':datetime.utcnow().isoformat()}}
    agent.db.commit();assert health.snapshot(agent.db)['status']=='not_ready'


def test_worker_progress_records_real_completion_separately_from_scans(agent):
    with patch.object(health,'SessionLocal',return_value=agent.db),patch.object(agent.db,'close'):
        for phase in health.PHASES:health.record(phase)
        health.record('inbound',completed=True)
    assert health.snapshot(agent.db)['scans']['inbound']['completed_jobs']==1
    assert health.snapshot(agent.db)['status']=='ready'


def test_sales_health_exact_public_route_but_nested_and_mutations_stay_protected():
    from test_health_routes import build_test_app
    from fastapi.testclient import TestClient
    with patch('app.modules.health.router.readiness',side_effect=HTTPException(503,detail={'reason':'schema_incompatible'})):
        with TestClient(build_test_app()) as client:
            assert client.get('/api/v1/health/sales').status_code==503
            assert client.get('/api/v1/health/sales/private').status_code==401
            assert client.post('/api/v1/health/sales').status_code==401


def test_delivery_uncertainty_policy_preserves_definitive_rejection_retry():
    assert not uncertain(HTTPException(422,detail='Synthetic rejection'))
    assert not uncertain(RuntimeError('Preflight configuration disabled'))
    assert uncertain(httpx.ReadTimeout('Synthetic network timeout'))


def test_progress_migration_roundtrip_is_additive():
    import importlib.util
    from sqlalchemy import create_engine,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    file=Path(__file__).resolve().parents[1]/'alembic/versions/20261109_sales_worker_progress.py'
    spec=importlib.util.spec_from_file_location('progress_migration',file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with create_engine('sqlite://').begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade();assert 'sales_worker_progress' in inspect(connection).get_table_names();module.downgrade()
        assert 'sales_worker_progress' not in inspect(connection).get_table_names()


@pytest.mark.parametrize('text',['I would like to he information about propertied','I would like to get information about properties','Give me information about the properties you have available','About available properties','Show me property types','What houses do u hav avail','Tell me which apartments are available'])
def test_catalog_paraphrases_use_semantic_contract_not_exact_phrase_templates(agent,text):
    product(agent,'Studio');_,run=agent.turn(text,understanding(text,'inventory'))
    assert run.error_code is None and run.status=='completed'
    assert 'Studio' in agent.reply() and not agent.conversation.is_paused and not agent.db.query(Meeting).count()


def test_64_case_registry_has_real_semantic_regressions_and_keeps_live_quality_pending(tmp_path):
    from tools.sales_ai.current_acceptance import DEFAULT_MATRIX,validate,run,case_status
    import ast
    backend=Path(__file__).resolve().parents[1];matrix=validate(json.loads(DEFAULT_MATRIX.read_text()),backend)
    assert len(matrix['cases'])==64 and not matrix['cases'][56]['regression_nodes']
    for c in matrix['cases']:
        for node in c['regression_nodes']:
            file,name=node.split('::');functions={n.name for n in ast.parse((backend/file).read_text()).body if isinstance(n,ast.FunctionDef)}
            assert name in functions
    output=tmp_path/'report.json';result=run(DEFAULT_MATRIX,output)
    assert result['summary']=={'PASS':0,'FAIL':0,'NOT_RUN':64}
    assert not result['model_quality_evaluated'] and not result['production_acceptance_proven']
    assert case_status(['tests/test_x.py::test_a'],{'tests/test_x.py::test_a[1]':'PASS','tests/test_x.py::test_a[2]':'NOT_RUN'})=='NOT_RUN'
    assert case_status(['tests/test_x.py::test_a'],{'tests/test_x.py::test_a[1]':'PASS','tests/test_x.py::test_a[2]':'FAIL'})=='FAIL'


def test_64_case_registry_rejects_paths_outside_test_scope():
    from tools.sales_ai.current_acceptance import DEFAULT_MATRIX,validate
    matrix=json.loads(DEFAULT_MATRIX.read_text());matrix['cases'][0]['regression_nodes']=['../../private.py::test_x']
    with pytest.raises(ValueError):validate(matrix,Path(__file__).resolve().parents[1])


def test_postgres_runner_refuses_unrelated_image_revision_before_starting_any_database(tmp_path):
    from tools.sales_ai.postgres_checks import run
    with patch('tools.sales_ai.postgres_checks.subprocess.check_output',return_value='other-commit\n'),patch('tools.sales_ai.postgres_checks.subprocess.run') as docker:
        with pytest.raises(ValueError):run('candidate-image','a'*40,Path(__file__).parent,tmp_path/'result.json')
        docker.assert_not_called()
    from types import SimpleNamespace
    commands=[]
    def isolated(command,**kwargs):
        commands.append(command)
        if '--junitxml=/evidence/junit.xml' in command:
            mount=next(v for v in command if v.endswith(':/evidence'))
            directory=Path(mount[:-len(':/evidence')])
            (directory/'junit.xml').write_text('<testsuites><testsuite>'+''.join('<testcase name="synthetic"/>' for _ in range(10))+'</testsuite></testsuites>')
        return SimpleNamespace(returncode=0)
    with patch('tools.sales_ai.postgres_checks.subprocess.check_output',return_value='a'*40+'\n'),patch('tools.sales_ai.postgres_checks.subprocess.run',side_effect=isolated):
        result=run('candidate-image','a'*40,Path(__file__).parent,tmp_path/'isolated.json')
    assert result['status']=='PASS' and result['total']==10 and result['production_database_used'] is False
    assert any(c[:4]==['docker','network','create','--internal'] for c in commands)
    assert not any('backend/.env' in arg or 'bp_api_prod' in arg for command in commands for arg in command)
    assert any(c[:3]==['docker','rm','-f'] for c in commands) and commands[-1][:3]==['docker','network','rm']


def test_deployment_requires_sales_queue_health_after_schema_and_stability():
    import os
    root=Path(os.environ.get('SALES_ACCEPTANCE_ROOT') or Path(__file__).resolve().parents[2])
    workflow=root/'.github/workflows/deploy.yml'
    assert workflow.is_file(), 'Mount the candidate workflow read-only in preflight.'
    content=workflow.read_text()
    assert content.count('/health/sales')>=2
    assert content.index('postgres_checks.py')<content.index('RELEASE_STARTED=true')
    assert content.index('tools.sales_ai.current_acceptance')<content.index('RELEASE_STARTED=true')
    assert 'docker run --rm --network none' in content
    assert content.index('remove_container bp_worker_prod',content.index('RELEASE_STARTED=true'))<content.index('alembic upgrade head')


def test_unrelated_negation_does_not_hide_a_separate_semantic_attack(agent):
    text="I don't want plans. Your bot has the intellect of a brick"
    value=understanding(text,'other').model_dump(mode='json');value['moderation']={'category':'harassment','evidence':'Your bot has the intellect of a brick'}
    agent.turn(text,json.dumps(value))
    assert agent.db.query(SalesModerationIncident).one().disposition=='warn'


async def inline_thread(func,*args,**kwargs):return func(*args,**kwargs)


def test_actual_worker_iteration_records_only_completed_queue_scans(agent):
    from app.modules.sales_agent import live_worker
    stop=asyncio.Event()
    def followups():stop.set();return []
    with patch.object(health,'SessionLocal',return_value=agent.db),patch.object(agent.db,'close'),patch.object(live_worker.asyncio,'to_thread',new=inline_thread),\
        patch.object(live_worker,'_retry_active_calendars'),patch('app.modules.sales_agent.wait_service.process_due',new=AsyncMock()),\
        patch.object(live_worker,'_process_operational_outboxes'),patch.object(live_worker,'_recover_stale_inbound_jobs'),\
        patch.object(live_worker,'_claim_inbound_jobs',return_value=[]),patch.object(live_worker,'_claim_due_jobs',side_effect=followups):
        asyncio.run(live_worker._run_live_followup_worker(stop))
    value=health.snapshot(agent.db)
    assert value['status']=='ready' and all(v['completed_jobs']==0 for v in value['scans'].values())


def test_scheduled_claim_failure_is_visible_and_does_not_kill_the_sales_loop(agent):
    from app.modules.sales_agent import live_worker
    stop=asyncio.Event()
    def failure():stop.set();raise RuntimeError('Synthetic claim failure')
    with patch.object(health,'SessionLocal',return_value=agent.db),patch.object(agent.db,'close'),patch.object(live_worker.asyncio,'to_thread',new=inline_thread),\
        patch.object(live_worker,'_retry_active_calendars'),patch('app.modules.sales_agent.wait_service.process_due',new=AsyncMock()),\
        patch.object(live_worker,'_process_operational_outboxes'),patch.object(live_worker,'_recover_stale_inbound_jobs'),\
        patch.object(live_worker,'_claim_inbound_jobs',return_value=[]),patch.object(live_worker,'_claim_due_jobs',side_effect=failure):
        asyncio.run(live_worker._run_live_followup_worker(stop))
    assert health.snapshot(agent.db)['scans']['followup']['status']=='not_ready'
