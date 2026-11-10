"""Evaluation isolation, real-engine integration and failure reporting; offline HTTP."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import socket
from types import SimpleNamespace as NS

import httpx
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from test_onboarding_revisions_and_money import context
from app.db.postgres import Base
from app.modules.ai_core.models import AIConfiguration
from app.modules.sales_agent.models import AgentRun, SalesConversation
from app.modules.sales_crm.models import Lead
from tools.sales_ai.evaluation import snapshot, encode, child_environment
from tools.sales_ai.evaluation_guard import Budget, EvaluationBlocked, guard
from tools.sales_ai.evaluation_checks import sanitize, turn_checks
from tools.sales_ai import evaluation_worker as worker


def add_config(db):
    db.add(AIConfiguration(company_id=None,openrouter_api_key='private-evaluation-key',
                           agent_ventas={'model':'openai/gpt-4o-mini'}));db.commit()


def test_snapshot_does_not_copy_leads_or_modify_source(context,tmp_path):
    db,company,user,project,profile,item=context
    add_config(db)
    before=db.query(Lead).count()
    data=snapshot(db.bind,company.id,project.id,tmp_path)
    assert data['project_name']==project.name
    assert data['approved_revision']==profile.published_snapshot['revision']
    assert 'leads' not in data['tables'] and 'users' not in data['tables']
    assert 'telnyx_configurations' not in data['tables']
    assert db.query(Lead).count()==before
    clone=create_engine('sqlite://')
    worker.hydrate(clone,json.loads(json.dumps(data,default=encode)))
    with sessionmaker(bind=clone)() as isolated:
        assert isolated.query(Lead).count()==0
        assert isolated.query(AIConfiguration).one().openrouter_api_key=='private-evaluation-key'
    clone.dispose()


def test_snapshot_rejects_wrong_tenant_and_unpublished_project(context,tmp_path):
    db,company,user,project,profile,item=context
    with pytest.raises(ValueError):snapshot(db.bind,'another-company',project.id,tmp_path)
    profile.published_snapshot=None;db.commit()
    with pytest.raises(ValueError):snapshot(db.bind,company.id,project.id,tmp_path)


def test_child_environment_excludes_production_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv('DATABASE_URL','postgresql://private-production')
    monkeypatch.setenv('TELNYX_API_KEY','private-production')
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS','private-production')
    monkeypatch.setenv('OPENROUTER_API_KEY','private-production')
    env=child_environment(str(tmp_path))
    assert env['DATABASE_URL'].startswith('sqlite:///')
    assert 'private-production' not in json.dumps(env)
    assert 'GOOGLE_APPLICATION_CREDENTIALS' not in env
    assert 'TELNYX_API_KEY' not in env
    assert env['PUBLIC_APP_URL']=='https://evaluation.invalid'


def test_guard_blocks_messaging_direct_ip_and_sync_http():
    budget=Budget(1)
    with guard(budget):
        with pytest.raises(EvaluationBlocked):
            asyncio.run(httpx.AsyncClient(trust_env=False).post('https://api.telnyx.com/v2/messages'))
        with pytest.raises(EvaluationBlocked):socket.getaddrinfo('smtp.example.com',443)
        with socket.socket() as s:
            with pytest.raises(EvaluationBlocked):s.connect(('127.0.0.1',5432))
        with pytest.raises(EvaluationBlocked):httpx.Client(trust_env=False).get('https://openrouter.ai')
    assert budget.calls==0 and budget.blocked==4


def test_call_budget_stops_before_extra_request():
    budget=Budget(1)
    req=httpx.Request('POST','https://openrouter.ai/api/v1/chat/completions')
    budget.authorize(req)
    with pytest.raises(EvaluationBlocked):budget.authorize(req)
    assert budget.calls==1


def test_report_never_promotes_machine_failure_or_exposes_keys(tmp_path):
    report={'cases':[{'case':'example','checks':[], 'turns':[{'turn':1,'reply':'secret-key',
             'checks':[{'check':'budget','status':'FAIL'}]}],
             'judge':{'assessments':[{'verdict':'PASS'}]}}]}
    result=worker.save_reports(tmp_path,report,['secret-key'])
    assert result['status']=='FAIL'
    assert 'secret-key' not in (tmp_path/'report.json').read_text()
    assert 'secret-key' not in (tmp_path/'report.md').read_text()
    assert sanitize({'api_key':'secret','model_request':{'content':'secret'}})=={}


def test_machine_checks_detect_lost_budget_and_wrong_parking():
    run=NS(error_code=None,input_snapshot={'understanding':{'requests':[{'topic':'inventory'}]}},
        output_snapshot={'workflow_version':'sales-current/1.0','metadata':{'composition':{'status':'accepted'}}})
    rows=turn_checks(run,'Available properties','budget',{'current':{}},0)
    assert next(c for c in rows if c['check']=='budget_captured')['status']=='FAIL'
    rows=turn_checks(run,'Available properties','parking',{},0)
    assert next(c for c in rows if c['check']=='parking_not_inventory')['status']=='FAIL'


def test_real_simulation_engine_preserves_interpretation_and_composition_trace(context,tmp_path,monkeypatch):
    db,company,user,project,profile,item=context
    add_config(db)
    data=snapshot(db.bind,company.id,project.id,tmp_path)
    clone=create_engine('sqlite://');worker.hydrate(clone,json.loads(json.dumps(data,default=encode)))
    # One bounded case still runs current_simulation.turn and all real engine stages.
    monkeypatch.setattr(worker,'CASES',[('inventory',[('What properties do you have available?',None)])])
    from app.modules.sales_agent.understanding_contract import Understanding
    def provider(request):
        payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
        context=json.loads(payload['messages'][1]['content'])
        if name=='sales_understanding':
            u=Understanding.model_validate({'version':'sales-understanding/1.0','requests':[{
              'id':'r1','topic':'inventory','polarity':'request','evidence':context['current_message']}],
              'all_of':['r1'],'alternatives':[],'constraints':[],'references':[],'preferences':[],
              'requires_clarification':False,'clarification_question':None,'confidence':.99})
            content=u.model_dump_json()
        elif name=='sales_commercial_composition':
            assert 'paragraphs' in payload['response_format']['json_schema']['schema']['required']
            blocks=[b for b in context['evidence_blocks'] if b['required']]
            content=json.dumps({'version':'sales-commercial-composer/1.0','opening':'direct',
                'blocks':[{'evidence_id':b['id'],'wording':'direct'} for b in blocks],
                'paragraphs':[[b['id']] for b in blocks], 'continuation_id':context['continuations'][0]['id']})
        else:raise AssertionError(name)
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self, **kw):
            super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kw)
    monkeypatch.setattr(httpx,'AsyncClient',Client)
    budget=Budget(10)
    with sessionmaker(bind=clone)() as isolated, guard(budget):
        reports,keys,guidance=asyncio.run(worker.evaluate(isolated,data,
            {'mode':'replay','max_turns':8,'judge':False},budget))
        assert reports[0]['complete'],reports
        row=reports[0]['turns'][0]
        assert all(c['status']=='PASS' for c in row['checks']),row
        assert row['interpretation_attempts'][0]['outcome']=='accepted'
        assert row['output']['metadata']['composition']['status']=='accepted'
        assert isolated.query(Lead).count()==1
        assert isolated.query(SalesConversation).one().channel=='simulation'
        assert isolated.query(AgentRun).one().mode=='simulation'
    assert budget.calls==2
    assert db.query(Lead).count()==0
    clone.dispose()


def test_machine_checks_do_not_accept_wrong_budget_or_negated_cash():
    run=NS(error_code=None,input_snapshot={'understanding':{}},output_snapshot={'workflow_version':'sales-current/1.0','metadata':{}})
    profile={'current':{'budget':{'value':'15000000 USD'},'financing':{'value':'No cash','status':'declared'}}}
    rows=turn_checks(run,'Thanks','budget',profile,0)
    assert next(c for c in rows if c['check']=='budget_captured')['status']=='FAIL'
    rows=turn_checks(run,'Thanks','cash',profile,0)
    assert next(c for c in rows if c['check']=='cash_captured')['status']=='FAIL'


def test_judge_cannot_omit_criteria_or_invent_turn_evidence(monkeypatch):
    from app.integrations import openrouter_client
    async def omitted(*args,**kwargs):return json.dumps({'assessments':[]})
    monkeypatch.setattr(openrouter_client,'generate_llm_response',omitted)
    with pytest.raises(ValueError):asyncio.run(worker.judge('key','model',[{'turn':1}],{}))
    async def invented(*args,**kwargs):
        return json.dumps({'assessments':[{'criterion':c,'verdict':'FAIL','evidence_turns':[99],'reason':'unavailable'}
            for c in ['answers_current_question','recognizes_corrections','avoids_repetition','commercial_helpfulness']]})
    monkeypatch.setattr(openrouter_client,'generate_llm_response',invented)
    with pytest.raises(ValueError):asyncio.run(worker.judge('key','model',[{'turn':1}],{}))


def test_source_snapshot_queries_are_select_only(context,tmp_path):
    from sqlalchemy import event
    db,company,user,project,profile,item=context
    add_config(db);seen=[]
    def record(conn,cursor,statement,*args):seen.append(statement)
    event.listen(db.bind,'before_cursor_execute',record)
    try:snapshot(db.bind,company.id,project.id,tmp_path)
    finally:event.remove(db.bind,'before_cursor_execute',record)
    assert seen and all(s.lstrip().upper().startswith('SELECT') for s in seen)


def test_model_call_count_includes_real_mock_transport_and_enforces_limit(monkeypatch):
    calls=[]
    async def request():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (calls.append(r) or httpx.Response(200,json={'usage':{'prompt_tokens':7,'completion_tokens':3,'cost':.001}}))),trust_env=False) as client:
            await client.post('https://openrouter.ai/api/v1/chat/completions')
            await client.post('https://openrouter.ai/api/v1/chat/completions')
    budget=Budget(1)
    with guard(budget):
        with pytest.raises(EvaluationBlocked):asyncio.run(request())
    assert len(calls)==1 and budget.calls==1
    assert budget.usage['prompt_tokens']==7


def test_actual_subprocess_uses_private_database_and_reports_missing_key(context,tmp_path):
    import os,subprocess,sys
    db,company,user,project,profile,item=context
    db.add(AIConfiguration(company_id=None,agent_ventas={'model':'openai/gpt-4o-mini'},openrouter_api_key=None));db.commit()
    storage=tmp_path/'snapshot';storage.mkdir()
    data=snapshot(db.bind,company.id,project.id,storage)
    source_path=tmp_path/'source.db';source=create_engine('sqlite:///'+str(source_path))
    worker.hydrate(source,json.loads(json.dumps(data,default=encode)))
    env=dict(os.environ,DATABASE_URL='sqlite:///'+str(source_path),ENVIRONMENT='test',PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    output=tmp_path/'result'
    result=subprocess.run([sys.executable,'-m','tools.sales_ai.evaluation','--company-id',company.id,
        '--project-id',project.id,'--output',str(output),'--max-calls','1','--no-judge'],
        env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==2,(result.stdout,result.stderr)
    report=json.loads((output/'report.json').read_text())
    assert report['status']=='ERROR' and report['error_code']=='ValueError'
    assert report['provider_calls']==0 and report['production_database_writes']==0
    with source.connect() as connection:
        assert connection.execute(select(func.count()).select_from(Lead.__table__)).scalar()==0
    source.dispose()


def test_stop_case_uses_real_control_path_without_model_or_delivery(context,tmp_path,monkeypatch):
    db,company,user,project,profile,item=context
    add_config(db);data=snapshot(db.bind,company.id,project.id,tmp_path)
    clone=create_engine('sqlite://');worker.hydrate(clone,json.loads(json.dumps(data,default=encode)))
    monkeypatch.setattr(worker,'CASES',[('opt_out',[('STOP','stop')])])
    budget=Budget(1)
    with sessionmaker(bind=clone)() as isolated, guard(budget):
        reports,keys,guidance=asyncio.run(worker.evaluate(isolated,data,{'mode':'replay','max_turns':1,'judge':False},budget))
        assert reports[0]['complete'],reports
        row=reports[0]['turns'][0]
        assert all(c['status']=='PASS' for c in row['checks']),row
        assert isolated.query(Lead).one().is_opt_out
    assert budget.calls==0
    assert db.query(Lead).count()==0
    clone.dispose()


def test_error_diagnostics_do_not_include_exception_or_sql_body():
    from tools.sales_ai.evaluation_checks import error_details
    try:raise ValueError('private-evaluation-key SQL confidential lead data')
    except ValueError as exc:result=error_details(exc)
    assert result['error_code']=='ValueError' and result['error_frames']
    assert 'private-evaluation-key' not in json.dumps(result)
    assert 'SQL confidential' not in json.dumps(result)


def test_adaptive_lead_only_sees_customer_visible_conversation():
    value=worker.visible_history('Welcome',[{'lead_message':'Hi','reply':'Hello',
        'understanding':{'hidden':'internal'},'output':{'prompt':'internal'},'checks':['internal']}])
    assert value=={'initial_agent_reply':'Welcome','turns':[{'lead':'Hi','agent':'Hello'}]}
    assert 'internal' not in json.dumps(value)
