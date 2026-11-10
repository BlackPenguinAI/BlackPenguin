"""Eligibility, public-only buyer driving and real sandbox persistence."""
from datetime import datetime,timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app.db.base
from app.db.postgres import Base
from app.core.config import settings
from tools.sales_ai.synthetic_fixtures import seed
from tools.sales_ai.booking_pilot import CASES,BOOKING_CASES,team,next_message
from app.modules.project_team.service import eligible_appointment_assignments,select_next_sales_user
from app.modules.sales_crm.scheduling import eligible_users_for_slot,create_agent_appointment
from app.modules.sales_crm.models import Lead,Meeting
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_agent.execution import sandbox

@pytest.fixture
def lab(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        yield db,seed(db,tmp_path/'materials')
    engine.dispose()

@pytest.mark.parametrize('scenario',CASES)
def test_real_eligibility_and_slots(lab,scenario):
    db,manifest=lab;clock=datetime.utcnow();rows=team(db,manifest,scenario,clock)
    pid=manifest['projects'][0]['id']
    eligible={a.user_id for a in eligible_appointment_assignments(db,pid)}
    expected={r['id'] for r in rows if r['scope']==('specific' if scenario=='one_project' else 'all')} if scenario in BOOKING_CASES|{'no_slots'} else set()
    assert eligible==expected
    start=(clock+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    available=eligible_users_for_slot(db,project_id=pid,starts_at=start,duration_minutes=30)
    assert set(available)==(expected if scenario in BOOKING_CASES else set())
    for project in manifest['projects'][1:]:
        other={a.user_id for a in eligible_appointment_assignments(db,project['id'])}
        assert other==(eligible if scenario in {'all_projects','alternative_slot','no_slots'} else set())


def test_public_buyer_selection_and_alternative():
    text='Verified visit options:\n\n1. 2026-11-12 at 10:00 AM (UTC, UTC+0000); Synthetic A\n\n2. 2026-11-12 at 11:00 AM (UTC, UTC+0000); Synthetic B\n\nWhich time?'
    message,action=next_message(text,[],alternative=True)
    assert action=='reject_first' and '11:00 AM' in message and '10:00 AM' not in message
    message,action=next_message('Please confirm your visit: 2026-11-12 at 11:00 AM',[])
    assert action=='confirm' and message.startswith('Yes')
    assert next_message('Verified visit options:\n\n1. 2026-11-12 at 10:00 AM',[],alternative=True)==(None,'no_alternative_offered')


def test_real_booking_persists_and_prevents_overlap(lab):
    db,manifest=lab;clock=datetime.utcnow();team(db,manifest,'all_projects',clock)
    pid=manifest['projects'][0]['id'];cid=manifest['company_id']
    lead=Lead(company_id=cid,project_id=pid,full_name='Synthetic Buyer',phone='+15550109999',is_demo=True)
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=cid,project_id=pid,lead_id=lead.id,channel='simulation',provider='simulation')
    db.add(conversation);db.commit()
    start=(clock+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    with sandbox(db,conversation,clock):
        meeting,user=create_agent_appointment(db,lead=lead,starts_at=start,duration_minutes=30,modality='in_person',emit_notification=False)
        db.commit()
        assert db.get(Meeting,meeting.id).assigned_sales_user_id==user.id
        assert not eligible_users_for_slot(db,project_id=pid,starts_at=start,duration_minutes=30)
        assert not eligible_users_for_slot(db,project_id=manifest['projects'][1]['id'],starts_at=start,duration_minutes=30)


def test_round_robin_function_works_with_fixture_sales(lab):
    db,manifest=lab;team(db,manifest,'all_projects',datetime.utcnow())
    pid=manifest['projects'][0]['id'];eligible=eligible_appointment_assignments(db,pid)
    assert select_next_sales_user(db,pid,for_appointments=True)==eligible[0].user_id


@pytest.mark.parametrize('scenario',CASES)
@pytest.mark.parametrize('omit_refs',[False,True])
def test_scripted_driver_reaches_real_coordinator_booking(lab,monkeypatch,scenario,omit_refs):
    import asyncio,json,httpx
    from unittest.mock import patch
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    from app.modules.sales_agent.understanding_contract import Understanding
    from tools.sales_ai.booking_pilot import evaluate_case
    from tools.sales_ai.evaluation_guard import Budget,guard
    from test_sales_active_integration import understanding
    db,manifest=lab
    db.add(AIConfiguration(id='pilot-config',company_id=None,openrouter_api_key='OFFLINE-ONLY',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    seen={}
    def provider(request):
        payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
        ctx=json.loads(payload['messages'][1]['content'])
        if name=='sales_understanding':
            text=ctx['current_message'];seen[text]=seen.get(text,0)+1
            if text.startswith(('Yes','Understood')):
                value=understanding(text,'other')
            elif 'first appointment:' in text or 'second appointment:' in text:
                expression='second appointment' if 'second appointment:' in text else 'first appointment'
                from test_sales_ai_group_d import typed,req,ref
                value=understanding(text,'appointment') if omit_refs else typed(text,[req('slot','appointment',text,ref='s')],[ref('s','appointment',expression)])
            else:
                value=understanding(text,'appointment')
                data=value.model_dump();data['visit']={'action':'request','evidence':text,'timing':None}
                if 'paying cash' in text:data['preferences']=[{'key':'financing','value':'cash','evidence':'paying cash','status':'declared'},{'key':'budget','value':'900000 USD','evidence':'My budget is 900,000 USD','status':'declared'}]
                if 'Bay Residence' in text:
                    data['references']=[{'id':'p','kind':'property','expression':'Bay Residence','evidence':'Bay Residence'}]
                    data['requests'][0]['reference_id']='p'
                if omit_refs and 'paying cash' in text:data['preferences']=[p for p in data['preferences'] if p['key']==('budget' if seen[text]==1 else 'financing')]
                value=Understanding.model_validate(data)
            if text.startswith('Understood') and omit_refs:
                data=value.model_dump();data['empathy']={'kind':'frustrated','evidence':text}
                value=Understanding.model_validate(data)
            if seen[text]>1:
                assert payload['response_format']['json_schema']['schema']['$defs']['Request']['properties']['evidence']['enum']
            content=value.model_dump_json()
        elif name=='sales_commercial_composition':
            rows=ctx['evidence_blocks'];content=json.dumps({'version':'sales-commercial-composer/1.0','opening':'direct',
                'blocks':[{'evidence_id':r['id'],'wording':'direct'} for r in rows],
                'paragraphs':[[r['id']] for r in rows],'continuation_id':ctx['continuations'][0]['id']})
        else:raise AssertionError('Unexpected model role: '+name)
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kwargs)
    budget=Budget(30)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,6))
    assert (result['stop_reason']=='booked')==(scenario in BOOKING_CASES),[(r.get('lead_message'),r.get('reply'),r.get('error_code')) for r in result['turns']]
    assert len(result['meetings'])==(1 if scenario in BOOKING_CASES else 0)
    if omit_refs:
        attempts=result['turns'][0]['interpretation_attempts']
        assert len(attempts)==2 and attempts[0]['validation_issues'][0]['type']=='payment_declaration_missing'
        if scenario not in BOOKING_CASES:
            acknowledgement=next(r for r in result['turns'] if r['action']=='acknowledge_unavailable')
            assert acknowledgement['understanding']['empathy'] is None
            assert acknowledgement['interpretation_attempts'][0]['normalizations'][0]['action']=='omit_unsupported_optional_affect'
            assert len(acknowledgement['interpretation_attempts'])==1
    assert all(c['status']=='PASS' for row in result['turns'] for c in row.get('checks',[])),result
    assert not any(c['status']=='FAIL' for c in result['checks']),{'checks':result['checks'],'replies':[r.get('reply') for r in result['turns']]}


def test_worker_exports_all_six_cases_and_redacts_key(tmp_path,monkeypatch):
    import json
    from app.db import postgres
    from tools.sales_ai.booking_pilot_worker import run
    from test_sales_synthetic_lab import mock_models
    engine=create_engine('sqlite:///'+str(tmp_path/'evaluation.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    secret='NEVER-EXPORT-BOOKING-KEY'
    options={'prepare_only':False,'max_calls':120,'max_turns':4,
        'credential':{'id':'global-config','key':secret,'pack':{'model':'test/offline'},
            'version_id':'published-version','version_number':1,'published_at':None}}
    path=tmp_path/'options.json';path.write_text(json.dumps(options));output=tmp_path/'results';output.mkdir()
    # This provider does not understand appointments: the worker must export
    # failures rather than manufacture reservations or mark the run successful.
    with mock_models():status=run(path,output)
    data=json.loads((output/'summary.json').read_text())
    assert status==2 and data['status']=='FAIL'
    assert [c['case'] for c in data['cases']]==list(CASES)
    assert data['lead_model'] is None and data['judge_model'] is None
    assert data['provider_calls']<=120 and data['production_database_writes']==data['lead_contacts']==0
    assert secret not in (output/'summary.json').read_text()
    assert secret not in (output/'report.json').read_text()
    assert (output/'synthetic-sales-results.zip').is_file()
    engine.dispose()
