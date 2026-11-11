"""Eight closing scripts through the shared core with fake provider HTTP only."""
import asyncio,json,re
from unittest.mock import patch
import httpx
import pytest
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.understanding_contract import Understanding
from tools.sales_ai.closing_pilot import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard


@pytest.mark.parametrize('scenario',CASES)
def test_closing_scripts_use_shared_core_and_durable_request_queue(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='closing-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    def provider(request):
        payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
        ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if name=='sales_understanding':
            if text.startswith('No other'):topics=['other']
            elif 'financing options' in text:topics=['financing']
            elif 'What is the price' in text:topics=['human','pricing']
            else:topics=['appointment']
            data=understanding(text,*topics).model_dump()
            if text.startswith('No other'):
                # Wrong model control proposals must not turn a goodbye into action.
                data['courtesy']={'kind':'farewell','evidence':text}
            if text.startswith('I do not want a visit'):data['visit']={'action':'decline','evidence':'I do not want a visit yet.'}
            if text.startswith('I would like to book'):
                data['visit']={'action':'request','evidence':text,'timing':{'date_from_evidence':'next seven days','timezone_evidence':'project timezone'}}
                data['preferences']=[dict(key='budget',value='900000 USD',evidence='My budget is 900,000 USD',status='declared'),dict(key='financing',value='cash',evidence='paying cash',status='declared')]
            if text.startswith('Understood'):
                data['wait']={'action':'decline','evidence':text}
            content=Understanding.model_validate(data).model_dump_json()
        elif name=='sales_commercial_composition':
            blocks=[b['id'] for b in ctx['evidence_blocks'] if b['required']]
            content=json.dumps(dict(version='sales-commercial-composer/1.0',opening='direct',blocks=[dict(evidence_id=i,wording='natural') for i in blocks],paragraphs=[[i] for i in blocks],continuation_id=ctx['continuations'][0]['id']))
        else:raise AssertionError(name)
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kwargs)
    budget=Budget(20)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,4))
    assert all(c['status']=='PASS' for t in result['turns'] for c in t['checks']),[(t['lead_message'],t['reply'],[c for c in t['checks'] if c['status']!='PASS']) for t in result['turns']]
    assert all(c['status']=='PASS' for c in result['checks'])



def test_closing_prepare_matches_evaluated_empty_sales_roster(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import postgres
    from app.core.config import settings
    from tools.sales_ai.booking_pilot_worker import run
    engine=create_engine('sqlite:///'+str(tmp_path/'lab.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine,autoflush=False))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    options=tmp_path/'options.json';options.write_text(json.dumps(dict(suite='closing-point',credential={},prepare_only=True,max_calls=96,max_turns=4)))
    output=tmp_path/'results';output.mkdir()
    assert run(options,output)==0
    report=json.loads((output/'summary.json').read_text())
    assert report['scenario_count']==8 and report['team']==[] and report['provider_calls']==0
