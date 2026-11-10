"""Synthetic catalog, resource bytes, current-engine dialogues and isolation."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import zipfile

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.db.base
from app.db.postgres import Base
from app.core.config import settings
from tools.sales_ai.synthetic_fixtures import seed, PROJECTS, brochure
from tools.sales_ai.synthetic_lab import configuration
from tools.sales_ai.synthetic_lab_worker import run, personas, material_checks
from tools.sales_ai.evaluation_guard import Budget, guard
from app.modules.projects.models import Project, ProjectSalesAsset, SalesAssetShare
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.models import AgentRun
from app.modules.ai_core.models import AIConfiguration, PromptVersion
from app.modules.sales_crm.models import Lead


@pytest.fixture
def catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        manifest=seed(db,tmp_path/'preview')
        yield db,manifest,tmp_path
    engine.dispose()


def test_matrix_is_approved_with_real_readable_scoped_resources(catalog):
    db,data,root=catalog
    assert len(data['projects'])==3
    assert [len(p['properties']) for p in data['projects']]==[1,2,3]
    from app.modules.projects.property_resource_service import read_resource,available
    combos=set()
    for project in data['projects']:
        row=db.get(Project,project['id'])
        assert row.profile.final_approved and row.profile.published_snapshot['company_id']==data['company_id']
        scoped=build_commercial_context(db,project=row,company_id=data['company_id'],lead_id='synthetic-scope-check',channel='simulation')
        assert {p['id'] for p in scoped['property_types']}=={p['id'] for p in project['properties']}
        for prop in project['properties']:
            combos.add((prop['gallery'],prop['pdf']))
            for resource in prop['resources']:
                asset=db.get(ProjectSalesAsset,resource['asset_id'])
                assert asset.property_type_id==prop['id'] and asset.project_id==project['id'] and available(asset)
                content,mime,_=read_resource(asset.source)
                assert content==(root/'preview'/resource['path']).read_bytes()
                if resource['kind']=='pdf':assert content.startswith(b'%PDF-1.4') and b'xref' in content
                else:assert content.count(b'data:image/png;base64,')==2
    assert combos=={(True,True),(True,False),(False,True),(False,False)}
    with pytest.raises(PermissionError):seed(db,root/'another')


def test_seed_rejects_non_sqlite_before_any_database_write(tmp_path):
    db=NS(get_bind=lambda:NS(dialect=NS(name='postgresql')))
    with pytest.raises(PermissionError):seed(db,tmp_path)


def test_configuration_read_uses_only_select_and_requires_published_global_version(catalog):
    db,_,_=catalog
    db.add(AIConfiguration(id='config',company_id=None,openrouter_api_key='private-lab-key',agent_ventas={'model':'wrong/draft'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=4,is_published=True,configuration={'model':'published/model'}))
    db.commit();queries=[]
    def record(conn,cursor,statement,*args):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',record)
    try:data=configuration(db.bind,'config')
    finally:event.remove(db.bind,'before_cursor_execute',record)
    assert data['pack']['model']=='published/model'
    assert all(s.lstrip().upper().startswith('SELECT') for s in queries)
    assert all('leads' not in s and 'telnyx' not in s for s in queries)


@pytest.mark.parametrize('key',['harbor','cedar','sierra'])
def test_buyer_personas_have_goals_but_no_hidden_resource_truth(catalog,key):
    _,data,_=catalog;project=next(p for p in data['projects'] if p['key']==key)
    values=personas(project);text=json.dumps(values)
    assert len(values)==3
    for prop in project['properties']:
        for resource in prop['resources']:assert resource['asset_id'] not in text
    assert 'approved_revision' not in text and 'raw_response' not in text


@contextmanager
def mock_models():
    """The actual engine calls the provider boundary; only HTTP responses are scripted."""
    def provider(request):
        payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
        ctx=json.loads(payload['messages'][1]['content'])
        if name=='evaluation_lead':
            system=payload['messages'][0]['content']
            persona=json.JSONDecoder().raw_decode(system.split('profile and goals: ',1)[1])[0]
            control=ctx['controller'];current=control['current_goal'];following=control['next_goal']
            reply=ctx['turns'][-1]['agent'] if ctx['turns'] else ''
            content=json.dumps({'response_status':'answered' if reply else 'pending',
                'response_evidence':reply[:500], 'retry_message':current['question'],
                'next_message':following['question'] if following else ''})
        elif name=='sales_understanding':
            text=ctx['current_message'];data={'version':'sales-understanding/1.0','requests':[],
                'all_of':[],'alternatives':[],'constraints':[],'references':[],'preferences':[],
                'requires_clarification':False,'clarification_question':None,'confidence':.99}
            for item in ctx['approved_context']['property_types']:
                name=item['property_type']
                if name in text:
                    data['references']=[{'id':'ref1','kind':'property','expression':name,'evidence':name}];break
            def req(topic,subject=None,ref=None,**kw):
                rid='r'+str(len(data['requests']))
                data['requests'].append({'id':rid,'topic':topic,'subject':subject,'polarity':'request','evidence':text,'reference_id':ref or ('ref1' if data['references'] else None),**kw});data['all_of'].append(rid)
            if 'photos and a' in text and 'brochure for ' in text:
                focus=text.split('brochure for ',1)[1].strip().rstrip('?')
                data['references']=[{'id':'ref1','kind':'property','expression':focus,'evidence':focus}]
                req('materials','photos','ref1');req('materials','brochure','ref1')
            elif 'parking' in text:req('property_details',detail_fields=['features'],feature='parking')
            elif 'bank financing' in text:
                req('property_details',detail_fields=['bedrooms'])
                data['preferences']=[{'key':'financing','value':'bank financing','evidence':text.split('.',1)[0],'status':'declared'}]
            elif 'bedrooms' in text:req('property_details',detail_fields=['bedrooms','area'] if 'floor area' in text else ['bedrooms'])
            elif 'cash' in text:data['preferences']=[{'key':'financing','value':'cash','evidence':text,'status':'declared'}]
            elif text=='Thanks':data['courtesy']={'kind':'acknowledgement','evidence':'Thanks'}
            else:req('inventory')
            content=Understanding.model_validate(data).model_dump_json()
        elif name=='sales_commercial_composition':
            rows=ctx['evidence_blocks']
            content=json.dumps({'version':'sales-commercial-composer/1.0','opening':'direct',
                'blocks':[{'evidence_id':r['id'],'wording':'direct'} for r in rows],
                'paragraphs':[[r['id']] for r in rows],'continuation_id':ctx['continuations'][0]['id']})
        else:raise AssertionError(name)
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kw)
    with patch.object(httpx,'AsyncClient',Client):yield


def test_complete_lab_runs_real_engine_in_private_worker_and_hides_credential(tmp_path,monkeypatch):
    # Worker engine must be in exactly the private options directory.
    from app.db import postgres
    engine=create_engine('sqlite:///'+str(tmp_path/'evaluation.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    secret='NEVER-EXPORT-THIS-LAB-CREDENTIAL'
    options={'prepare_only':False,'max_calls':180,'max_turns':5,'judge':False,'lead_model':None,
        'credential':{'id':'global-config','key':secret,'pack':{'model':'test/offline'},
                      'version_id':'published-version','version_number':1,'published_at':None}}
    path=tmp_path/'options.json';path.write_text(json.dumps(options));output=tmp_path/'results'
    with mock_models():code=run(path,output)
    summary=json.loads((output/'summary.json').read_text())
    assert summary['project_count']==3 and summary['property_count']==6
    assert summary['scenario_count']==9 and summary['provider_calls']<=180
    assert summary['blocked_network_calls']==0
    assert summary['status']=='PASS',summary
    assert code==0
    with zipfile.ZipFile(output/'synthetic-sales-results.zip') as z:
        assert z.testzip() is None
        assert all(secret.encode() not in z.read(name) for name in z.namelist())
        assert not any(name.endswith('.db') or 'options.json' in name for name in z.namelist())
    with sessionmaker(bind=engine)() as db:
        assert db.query(Lead).count()==9
        counts=sum(len(json.loads((output/p['report']).read_text())['cases'][i]['turns'])
                   for p in summary['projects'] for i in range(3))
        assert db.query(AgentRun).count()==counts
        assert 18 <= counts <= 54
    assert summary['lead_controller_metrics']['finished']==9
    assert summary['lead_controller_metrics']['role_violations_delivered']==0
    engine.dispose()


@pytest.mark.parametrize('text', ["You can message here if another question comes up.",
    "You're welcome. Feel free to message again whenever you have another question."])
def test_backend_courtesy_is_not_mislabeled_as_foreign_language(text):
    from app.modules.sales_agent.language_policy import detect
    assert not detect(text,output=True).needs_reentry



def test_prepare_only_cli_never_reads_source_database_or_calls_model(tmp_path):
    import os,subprocess,sys
    env=dict(os.environ, DATABASE_URL='postgresql://unreachable.invalid/do-not-connect')
    output=tmp_path/'prepared'
    result=subprocess.run([sys.executable,'-m','tools.sales_ai.synthetic_lab','--prepare-only','--output',str(output)],
        cwd=Path(__file__).resolve().parents[1],env={**env,'PYTHONPATH':str(Path(__file__).resolve().parents[1])},
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout
    data=json.loads((output/'summary.json').read_text())
    assert data['status']=='PREPARED' and data['provider_calls']==0
    assert data['project_count']==3 and data['property_count']==6
    assert data['production_database_writes']==data['lead_contacts']==0


def test_resource_audit_detects_wrong_project_share(catalog):
    db,data,_=catalog
    project=data['projects'][0];other=data['projects'][1]
    from app.modules.sales_agent.models import SalesConversation
    from datetime import datetime,timedelta
    lead=Lead(company_id=data['company_id'],project_id=project['id'],full_name='Synthetic',phone='+15550109999')
    db.add(lead);db.flush()
    conv=SalesConversation(company_id=data['company_id'],project_id=project['id'],lead_id=lead.id,channel='simulation')
    db.add(conv);db.flush()
    run=AgentRun(conversation_id=conv.id,event_id='scope-regression',mode='simulation',model='test',graph_version='test',toolset_version='test',prompt_snapshot={})
    db.add(run);db.flush()
    asset=db.get(ProjectSalesAsset,other['properties'][0]['resources'][0]['asset_id'])
    db.add(SalesAssetShare(company_id=data['company_id'],project_id=other['id'],lead_id=lead.id,
        source_id=asset.source_id,sales_asset_id=asset.id,token_hash='synthetic-wrong-project-token',expires_at=datetime.utcnow()+timedelta(days=1)))
    db.flush()
    case={'case':'new_buyer','turns':[{'run_id':run.id}],'checks':[]}
    material_checks(db,project,[case])
    assert next(c for c in case['checks'] if c['check']=='shared_resources_belong_to_active_project')['status']=='FAIL'
