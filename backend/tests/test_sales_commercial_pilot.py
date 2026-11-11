"""Eight commercial scripts use the shared coordinator; only model HTTP is mocked."""
import asyncio,json,re
from unittest.mock import patch
import httpx
import pytest
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.understanding_contract import Understanding
from tools.sales_ai.commercial_pilot import CASES,prepare,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard


@pytest.mark.parametrize('scenario',CASES)
def test_commercial_scripts_use_shared_engine_and_scoped_facts(lab,scenario):
    db,manifest=lab;prepare(db,manifest)
    db.add(AIConfiguration(id='commercial-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    seen={}
    def provider(request):
        payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
        ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if name=='sales_understanding':
            seen[text]=seen.get(text,0)+1
            topic='other' if text.startswith('No other') else 'financing' if re.search('financing|down payment|reserve',text,re.I) else 'pricing'
            data=understanding(text,topic).model_dump()
            if text.startswith('No other'):
                data['courtesy']={'kind':'farewell','evidence':text}
                data['empathy']={'kind':'frustrated','evidence':text}
            else:
                match=re.search(r'(?:My budget is|My total purchase budget is) ([\d,]+) (USD|EUR)',text)
                if match:data['preferences'].append(dict(key='budget',value=match[1]+' '+match[2],evidence=match[0],status='declared'))
                if 'cash' in text:
                    quote='I have cash available' if 'I have cash available' in text else 'I will pay cash'
                    data['preferences'].append(dict(key='financing',value='cash',evidence=quote,status='declared'))
                elif 'I need financing' in text:data['preferences'].append(dict(key='financing',value='financing',evidence='I need financing',status='declared'))
                if 'for a down payment' in text:data['preferences'].append(dict(key='budget',value='50000 USD',evidence=text,status='declared'))
            if text.startswith('My total purchase budget'):
                data['requests']=[dict(id='r0',topic='financing',polarity='request',evidence=text)]
                data['all_of']=['r0']
            if scenario=='cash_available' and seen[text]>1 and not text.startswith('No other'):
                data['requests'][0]['topic']='inventory'
            if scenario=='cash_available' and seen[text]==1 and not text.startswith('No other'):
                data['preferences']=[p for p in data['preferences'] if p['key']!='financing']
                data['requests'][0]['topic']='financing'
                data['requests'][0]['evidence']='I have cash available and do not need financing.'
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
    assert all(c['status']=='PASS' for t in result['turns'] for c in t['checks']),[(t['reply'],[c for c in t['checks'] if c['status']!='PASS']) for t in result['turns']]
    assert all(c['status']=='PASS' for c in result['checks'])



def test_commercial_worker_prepare_is_private_and_exports_eight_scripts(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import postgres
    from app.core.config import settings
    from tools.sales_ai.booking_pilot_worker import run
    engine=create_engine('sqlite:///'+str(tmp_path/'lab.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine,autoflush=False))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    options=tmp_path/'options.json';options.write_text(json.dumps(dict(suite='commercial-point',credential={},prepare_only=True,max_calls=96,max_turns=3)))
    output=tmp_path/'results';output.mkdir()
    assert run(options,output)==0
    data=json.loads((output/'summary.json').read_text())
    assert data['status']=='PREPARED' and data['scenario_count']==8 and data['provider_calls']==0
    catalog=json.loads((output/'catalog.json').read_text())
    assert catalog['projects'][2]['published_payment_methods']==['Cash only']
    assert (output/'synthetic-sales-results.zip').is_file()
