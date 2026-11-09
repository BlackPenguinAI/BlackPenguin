import json
from datetime import datetime, timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.db.base
from app.db.postgres import Base, get_db
from app.modules.auth.deps import get_current_user
from app.modules.users.models import User, UserRole
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead
from app.modules.governance.models import PlatformAuditEvent, DataExportAuditEvent
from app.modules.sales_agent.models import SalesConversation, SalesConversationLeadContext, SalesMessage, AgentRun, OutboundMessage, SalesInboundJob
from app.modules.sales_agent.monitor import router, ChatExport, redact
from app.modules.sales_agent.live_service import _prepare_run
from app.modules.sales_agent.turn_trace import dispatch_trace
from test_onboarding_revisions_and_money import context as published_project


@pytest.fixture
def monitor():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); db = sessionmaker(bind=engine)()
    company = Company(name='Company A'); other = Company(name='Company B')
    db.add_all([company, other]); db.flush()
    project = Project(company_id=company.id, name='Project A')
    foreign = Project(company_id=other.id, name='Project B')
    actor = User(email='staff@example.test', hashed_password='unused', role=UserRole.SUPERADMIN, is_active=True)
    db.add_all([project, foreign, actor]); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name='Lead A', phone='+12025550123')
    second = Lead(company_id=company.id, project_id=project.id, full_name='Lead B', phone='+12025550124')
    db.add_all([lead,second]); db.flush()
    conv = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id, provider='telnyx', channel='sms', is_paused=False)
    db.add(conv); db.flush()
    inbound = SalesMessage(conversation_id=conv.id, channel='sms', direction='inbound', role='user', content='Please send a brochure', metadata_json={'lead_id':lead.id}, created_at=datetime(2026,1,1))
    db.add(inbound); db.flush()
    run = AgentRun(conversation_id=conv.id, event_id='event-a', mode='live', status='completed', graph_version='v1', toolset_version='v1', model='example/model', prompt_snapshot={'system':'Historical applied prompt', 'api_key':'DO_NOT_EXPORT'}, input_snapshot={'message_id':inbound.id}, output_snapshot={'reply':'Original recorded response'})
    db.add(run); db.flush()
    outbound = SalesMessage(conversation_id=conv.id, channel='sms', direction='outbound', role='assistant', content='Recorded reply', provider_message_id='provider-a', status='sent', metadata_json={'lead_id':lead.id,'agent_run_id':run.id}, created_at=datetime(2026,1,2))
    db.add_all([outbound, SalesInboundJob(conversation_id=conv.id,message_id=inbound.id,status='processed'), OutboundMessage(conversation_id=conv.id,agent_run_id=run.id,idempotency_key='out-a',channel='sms',provider='telnyx',content='Recorded reply',status='delivered',provider_message_id='provider-a')]); db.commit()
    app = FastAPI(); app.include_router(router,prefix='/monitor')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    client = TestClient(app)
    scope = f'company_id={company.id}&project_id={project.id}&lead_id={lead.id}'
    yield db, client, actor, company, project, foreign, lead, second, conv, inbound, outbound, run, scope, app
    client.close(); db.close(); engine.dispose()


@pytest.mark.parametrize('role',[UserRole.ADMIN,UserRole.SALES,UserRole.MKT,UserRole.ASSISTANT])
@pytest.mark.parametrize('endpoint',[
    '/companies', '/projects?company_id=x', '/leads?company_id=x&project_id=y',
    '/conversations?company_id=x&project_id=y&lead_id=z',
    '/conversations/fake?company_id=x&project_id=y&lead_id=z',
    '/export-schema', '/conversations/fake/export?company_id=x&project_id=y&lead_id=z',
])
def test_tenant_roles_cannot_read_or_export(monitor,role,endpoint):
    _, client, actor, *_ = monitor
    actor.role = role
    assert client.get('/monitor'+endpoint).status_code == 403


def test_anonymous_access_is_rejected(monitor):
    *_,app = monitor
    app.dependency_overrides.pop(get_current_user)
    assert TestClient(app).get('/monitor/companies').status_code == 401


def test_filters_and_every_read_are_audited_without_sales_mutation(monitor):
    db,client,actor,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_ = monitor
    assert client.get('/monitor/companies').headers['cache-control']=='no-store'
    projects=client.get('/monitor/projects?company_id='+company.id).json()
    assert [p['id'] for p in projects]==[project.id]
    assert len(client.get(f'/monitor/leads?company_id={company.id}&project_id={project.id}').json()['items'])==2
    assert client.get('/monitor/conversations?'+scope).json()[0]['id']==conv.id
    assert db.query(PlatformAuditEvent).count()==4
    assert db.get(SalesMessage,inbound.id).content=='Please send a brochure'
    assert not conv.is_paused


def test_scope_tampering_returns_404(monitor):
    _,client,_,company,project,foreign,lead,second,conv,*_ = monitor
    for suffix in ('','/export'):
        response=client.get(f'/monitor/conversations/{conv.id}{suffix}?company_id={foreign.company_id}&project_id={project.id}&lead_id={lead.id}')
        assert response.status_code==404
        response=client.get(f'/monitor/conversations/{conv.id}{suffix}?company_id={company.id}&project_id={foreign.id}&lead_id={lead.id}')
        assert response.status_code==404


def test_incremental_polling_and_delivery_updates(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    url=f'/monitor/conversations/{conv.id}?{scope}'
    first=client.get(url+'&limit=1').json()
    assert first['has_more'] and first['messages'][0]['id']==inbound.id
    second_page=client.get(url+'&after='+first['next_cursor']).json()
    assert [m['id'] for m in second_page['messages']]==[outbound.id]
    outbound.status='delivered';conv.is_paused=True;conv.pause_reason='Manual staff review';db.commit()
    poll=client.get(url+'&after='+outbound.id).json()
    assert poll['messages']==[] and poll['delivery_statuses'][0]['status']=='delivered'
    assert poll['is_paused'] and poll['pause_reason']=='Manual staff review'
    assert client.get(url+'&after=foreign-cursor').status_code==409
    assert client.get(url+'&limit=201').status_code==422


def test_export_is_complete_versioned_redacted_and_audited(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    r=client.get(f'/monitor/conversations/{conv.id}/export?{scope}')
    assert r.status_code==200 and 'attachment;' in r.headers['content-disposition']
    value=ChatExport.model_validate(r.json())
    assert value.timezone=='UTC' and len(value.messages)==2
    assert len(value.runs)==1 and len(value.inbound_jobs)==1 and len(value.outbound_deliveries)==1
    assert value.runs[0]['prompt_snapshot']['system']=='Historical applied prompt'
    assert 'DO_NOT_EXPORT' not in r.text and '[REDACTED]' in r.text
    assert value.missing_evidence and value.runs[0]['missing_evidence']
    assert db.query(DataExportAuditEvent).one().filters_json['company_id']==company.id
    assert db.query(PlatformAuditEvent).filter_by(event_type='monitor.export').count()==1
    assert client.get('/monitor/export-schema').json()['properties']['schema_version']['const']==value.schema_version


def test_context_aware_history_does_not_mix_opportunities(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    db.add(SalesConversationLeadContext(conversation_id=conv.id,lead_id=lead.id,is_active=False))
    db.add(SalesConversationLeadContext(conversation_id=conv.id,lead_id=second.id,is_active=True))
    conv.lead_id=second.id
    db.add(SalesMessage(conversation_id=conv.id,channel='sms',direction='inbound',role='user',content='OTHER OPPORTUNITY',metadata_json={'lead_id':second.id}))
    db.add(SalesMessage(conversation_id=conv.id,channel='sms',direction='inbound',role='user',content='UNATTRIBUTED',metadata_json={}))
    db.commit()
    assert client.get('/monitor/conversations?'+scope).json()[0]['id']==conv.id
    value=client.get(f'/monitor/conversations/{conv.id}/export?{scope}').json()
    assert [m['id'] for m in value['messages']]==[inbound.id,outbound.id]
    assert 'OTHER OPPORTUNITY' not in json.dumps(value)
    assert 'UNATTRIBUTED' not in json.dumps(value)
    assert any('excluded' in m for m in value['missing_evidence'])


@pytest.mark.parametrize('value',[
    {'access_token':'sensitive'}, {'nested':{'Authorization':'Bearer sensitive'}},
    {'api_key':'sensitive'}, {'token':'sensitive'}, {'cookie':'sensitive'},
    {'text':'secret=sensitive'}, {'url':'https://example.test/file?access_token=sensitive'},
    {'text':'Bearer sensitive'}, {'text':'eyJfoo.eyJbar.signature'},
    {'text':'{"api_key": "sensitive"}'}, {'text':'https://user:sensitive@example.test/path'},
    {'text':'https://example.test/api/v1/projects/shared-assets/sensitive'},
])
def test_secret_redaction(value):
    result=json.dumps(redact(value))
    assert 'sensitive' not in result and 'eyJfoo' not in result
    assert '[REDACTED]' in result


def test_new_run_captures_context_and_retry_preserves_attempts(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,*_=monitor
    run=_prepare_run(db,conversation=conv,event_id='new-turn',message_id=inbound.id,model='deterministic/appointment-routing')
    assert run.input_snapshot['turn_trace']['company_id']==company.id
    assert 'approved_context' in run.input_snapshot['turn_trace']
    run.status='failed';db.commit()
    retry=_prepare_run(db,conversation=conv,event_id='new-turn',message_id=inbound.id)
    assert retry.id==run.id and len(retry.input_snapshot['trace_attempts'])==2
    retry.status='completed';db.commit()
    assert _prepare_run(db,conversation=conv,event_id='new-turn',message_id=inbound.id) is None


def test_deterministic_dispatch_trace_correlates_and_preserves_transformation(monitor):
    _,_,_,_,_,_,lead,_,conv,*_=monitor
    evidence=dispatch_trace(conv,lead,None,'manual_reply','Proposed','Final')
    assert evidence['trace_id'] and evidence['agent_run_id'] is None
    assert evidence['lead_id']==lead.id and evidence['proposed_reply']=='Proposed' and evidence['final_reply']=='Final'


def test_retry_of_legacy_failed_run_keeps_original_evidence(monitor):
    db,client,actor,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,app=monitor
    run.status='failed';run.error_code='historical-error';db.commit()
    retried=_prepare_run(db,conversation=conv,event_id=run.event_id,message_id=inbound.id)
    historical=retried.input_snapshot['trace_attempts'][0]
    assert historical['historical_input']['message_id']==inbound.id
    assert historical['output_snapshot']['reply']=='Original recorded response'
    assert historical['prompt_snapshot']['system']=='Historical applied prompt'
    assert historical['error_code']=='historical-error'


def test_actual_dispatch_persists_trace_and_exact_provider_body(published_project):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.modules.sales_agent.live_service import _dispatch
    db,company,user,project,profile,item=published_project
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Trace lead',phone='+12025550111')
    db.add(lead);db.flush()
    conv=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms',provider='telnyx',is_paused=False)
    db.add(conv);db.flush()
    run=_prepare_run(db,conversation=conv,event_id='dispatch-trace',message_id='recorded-inbound',model='deterministic/catalog')
    provider=AsyncMock(return_value={'sid':'trace-provider','status':'sent'})
    with patch('app.modules.sales_agent.live_service.send_sms',provider),patch('app.modules.sales_agent.live_service.send_message',provider):
        message=asyncio.run(_dispatch(db,conversation=conv,lead=lead,content='Price: 30,000 USD.',role='assistant',agent_run_id=run.id,metadata={'event_kind':'agent_reply','inbound_message_id':'recorded-inbound'}))
    trace=message.metadata_json['turn_trace']
    assert trace['trace_id']==run.id and trace['inbound_message_id']=='recorded-inbound'
    assert trace['proposed_reply']=='Price: 30,000 USD.'
    assert trace['final_reply']==message.content==provider.call_args.kwargs['body']
    assert run.input_snapshot['turn_trace']['approved_context']['approved_revision'] is not None


@pytest.mark.parametrize('method',['post','put','patch','delete'])
def test_monitor_has_no_mutating_routes(monitor,method):
    _,client,*_=monitor
    assert getattr(client,method)('/monitor/companies').status_code==405


def test_invalid_filter_scope_is_not_a_database_error(monitor):
    _,client,_,company,project,foreign,*_=monitor
    assert client.get('/monitor/projects?company_id=missing').status_code==404
    assert client.get(f'/monitor/leads?company_id={company.id}&project_id={foreign.id}').status_code==404


def test_equal_timestamp_cursor_has_stable_order_and_no_gaps(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    inbound.created_at=outbound.created_at=datetime(2026,1,1)
    db.commit()
    url=f'/monitor/conversations/{conv.id}?{scope}&limit=1'
    first=client.get(url).json()
    next_page=client.get(url+'&after='+first['next_cursor']).json()
    assert [first['messages'][0]['id'],next_page['messages'][0]['id']]==sorted([inbound.id,outbound.id])
    assert first['messages'][0]['created_at'].endswith('+00:00')


def test_failed_deterministic_delivery_is_exported_without_provider_id(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    from unittest.mock import AsyncMock, patch
    import asyncio
    from app.modules.sales_agent.live_service import _dispatch
    with patch('app.modules.sales_agent.live_service.send_sms',AsyncMock(side_effect=RuntimeError('provider offline'))):
        with pytest.raises(RuntimeError):
            asyncio.run(_dispatch(db,conversation=conv,lead=lead,content='Recorded deterministic response',role='assistant',agent_run_id=None,metadata={'event_kind':'deterministic_test','inbound_message_id':inbound.id}))
    failed=db.query(SalesMessage).filter_by(status='failed').one()
    assert failed.metadata_json['outbound_message_id']
    assert failed.metadata_json['turn_trace']['input_evidence']['approved_context']
    value=client.get(f'/monitor/conversations/{conv.id}/export?{scope}').json()
    delivery=next(d for d in value['outbound_deliveries'] if d['id']==failed.metadata_json['outbound_message_id'])
    assert delivery['status']=='failed' and delivery['provider_message_id'] is None
    assert delivery['content']==failed.content


def test_trace_failure_rolls_back_only_its_savepoint(monitor):
    from unittest.mock import patch
    from sqlalchemy import text
    from app.modules.sales_agent.turn_trace import capture_input
    db,_,_,company,_,_,_,_,conv,*_=monitor
    company.name='Pending business edit'
    def broken_context(*args,**kwargs):
        db.execute(text('SELECT * FROM missing_trace_table'))
    with patch('app.modules.sales_agent.commercial_context.build_commercial_context',side_effect=broken_context):
        evidence=capture_input(db,conv)
    assert evidence['missing']==['approved_context']
    db.commit()
    assert db.get(Company,company.id).name=='Pending business edit'
    assert db.execute(text('SELECT 1')).scalar()==1


@pytest.mark.parametrize('mode',['valid','tenant','inactive','invalid_signature','expired'])
def test_monitor_with_real_jwt_and_tenant_middleware(monitor,mode):
    from jose import jwt
    from app.core.config import settings
    from app.core.middleware import MultiTenantMiddleware
    db,_,actor,company,*_=monitor
    if mode=='tenant':
        actor.role=UserRole.ADMIN;actor.company_id=company.id
    if mode=='inactive':
        actor.is_active=False
    db.commit()
    app=FastAPI();app.include_router(router,prefix='/api/v1/monitor');app.add_middleware(MultiTenantMiddleware)
    app.dependency_overrides[get_db]=lambda:db
    expiry=datetime.utcnow()+timedelta(minutes=-1 if mode=='expired' else 5)
    token=jwt.encode({'sub':actor.email,'role':actor.role.value,'company_id':actor.company_id,'exp':expiry},'wrong-key' if mode=='invalid_signature' else settings.SECRET_KEY,algorithm=settings.ALGORITHM)
    with TestClient(app) as client:
        response=client.get('/api/v1/monitor/companies',headers={'Authorization':'Bearer '+token})
    expected=200 if mode=='valid' else 403 if mode=='tenant' else 401
    assert response.status_code==expected


def test_real_graph_keeps_model_proposal_policy_and_approved_context(published_project):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.sales_agent.service import _legacy_simulate_turn as simulate_turn
    db,company,user,project,profile,item=published_project
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Graph evidence',phone='+12025550133',is_demo=True,consent_status='granted')
    db.add_all([lead,AIConfiguration(company_id=company.id,openrouter_api_key='mock-only')]);db.commit()
    raw_reply='The price is 30,000 USD.'
    model_output=json.dumps({'reply':raw_reply,'primary_intent':'request_pricing','intent_confidence':.99,'extracted_facts':[],'proposed_actions':[{'type':'answer_question'}],'requires_human':False})
    with patch('app.modules.sales_agent.graph.generate_llm_response',AsyncMock(return_value=model_output)) as model:
        result=asyncio.run(simulate_turn(db,company_id=company.id,lead_id=lead.id,inbound_text='What is the starting price?'))
    run=db.get(AgentRun,result['run_id'])
    assert model.await_count==1
    assert run.output_snapshot['model_proposed_reply']==raw_reply
    assert run.output_snapshot['reply']!=raw_reply
    assert run.output_snapshot['response_policy_trace']['primary_intent']=='request_pricing'
    assert run.input_snapshot['graph_commercial_context']['approved_revision'] is not None
    assert run.prompt_snapshot['system_prompt']
    assert run.input_snapshot['model_request']['messages']==model.call_args.args[2]
    assert run.input_snapshot['model_request']['model']==model.call_args.args[1]
    assert 'mock-only' not in json.dumps(run.input_snapshot)


def test_failed_model_request_keeps_applied_prompt_not_later_settings(published_project):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.sales_agent.graph import build_sales_graph
    db,company,user,project,profile,item=published_project
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Failed graph',phone='+12025550134',consent_status='granted')
    db.add_all([lead,AIConfiguration(company_id=company.id,openrouter_api_key='mock-only')]);db.flush()
    conv=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms',provider='telnyx',is_paused=False)
    db.add(conv);db.commit()
    run=_prepare_run(db,conversation=conv,event_id='failed-provider-test',message_id='recorded-input')
    with patch('app.modules.sales_agent.graph.generate_llm_response',AsyncMock(side_effect=RuntimeError('model offline'))) as model:
        with pytest.raises(RuntimeError):
            asyncio.run(build_sales_graph(db).ainvoke({'event_id':run.event_id,'mode':'live','conversation_id':conv.id,'company_id':company.id,'project_id':project.id,'lead_id':lead.id,'channel':'sms','inbound_text':'Hello'}))
    db.rollback();db.refresh(run)
    assert run.prompt_snapshot['system_prompt']
    assert run.model==model.call_args.args[1]
    assert run.input_snapshot['model_request']['messages']==model.call_args.args[2]
    assert 'mock-only' not in json.dumps(run.input_snapshot)
