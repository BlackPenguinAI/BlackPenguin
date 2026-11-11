"""Offline provider contract tests; never claim these measure a real model."""
import asyncio,json,re
from datetime import datetime,timedelta
from unittest.mock import patch
import httpx
import pytest
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.understanding_contract import Understanding,BUYER_SEGMENTS
from tools.sales_ai.compact_battery import CASES,SPECS,PERSONAS,evaluate_case,public_next,team
from tools.sales_ai.evaluation_guard import Budget,guard


def provider(request):
    payload=json.loads(request.content);name=payload['response_format']['json_schema']['name']
    ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
    if name=='sales_understanding':
        if 'appointment:' in text or text.startswith(('Yes','Understood')):topics=['appointment']
        elif 'arrange an in-person visit' in text or 'I do not want a visit' in text:topics=['appointment']
        elif 'photos' in text or 'brochure PDF' in text:topics=['materials']
        elif 'financing' in text or 'down payment' in text or 'reserve' in text:topics=['financing']
        elif 'located' in text:topics=['location','delivery'] if 'delivery' in text else ['location']
        elif 'guarantee' in text:topics=['other']
        elif 'Is Summit Villa available' in text:topics=['inventory']
        elif 'Valley Apartment' in text:topics=['pricing','inventory']
        else:topics=['catalog']
        data=understanding(text,*topics,subjects={0:'photos' if 'photos' in text else 'brochure'} if topics==['materials'] else None).model_dump()
        properties=[n for n in ['Bay Residence','Cedar Loft','Cedar Studio','Ridge Townhome','Summit Villa','Valley Apartment'] if n in text]
        for i,n in enumerate(properties):data['references'].append(dict(id='p'+str(i),kind='property',expression=n,evidence=n))
        if len(properties)==1:
            for r in data['requests']:r['reference_id']='p0'
        if 'Please compare' in text:
            data['comparison']=dict(request_id='r0',reference_ids=['p0','p1'],include_current=False,include_all=False,criteria=['general'],evidence=text)
        match=re.search(r'(?:My budget is|My total purchase budget is) ([\d,]+) USD',text)
        if match:data['preferences'].append(dict(key='budget',value=match[1]+' USD',evidence=match[0],status='declared'))
        for quote,value in [('paying cash','cash'),('I need financing','financing')]:
            if quote in text:data['preferences'].append(dict(key='financing',value=value,evidence=quote,status='declared'))
        for p in PERSONAS:
            if p['motive'] and p['motive'] in text:data['preferences'].append(dict(key='buyer_type',value=p['segment'],evidence=p['motive'],status='declared'))
        if 'arrange an in-person visit' in text:
            data['visit']=dict(action='request',evidence=text,timing=dict(date_from_evidence='next seven days',timezone_evidence='project timezone'))
        if text.startswith('I do not want a visit'):data['visit']=dict(action='decline',evidence=text)
        if text.startswith('Understood'):data['wait']=dict(action='decline',evidence=text)
        content=Understanding.model_validate(data).model_dump_json()
    elif name=='sales_commercial_composition':
        blocks=[b['id'] for b in ctx['evidence_blocks'] if b['required']]
        content=json.dumps(dict(version='sales-commercial-composer/1.0',opening='direct',blocks=[dict(evidence_id=i,wording='natural') for i in blocks],paragraphs=[[i] for i in blocks],continuation_id=ctx['continuations'][0]['id']))
    else:raise AssertionError(name)
    return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})


@pytest.mark.parametrize('scenario',CASES)
def test_compact_scripts_exercise_real_core_and_assert_observable_outcomes(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='compact-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kwargs)
    budget=Budget(30)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    failures=[(t.get('action'),t.get('reply'),[c for c in t.get('checks',[]) if c['status']!='PASS']) for t in result['turns'] if any(c['status']!='PASS' for c in t.get('checks',[]))]
    final=[c for c in result['checks'] if c['status']!='PASS']
    assert not failures and not final,{'turns':failures,'final':final}
    assert 3<=len(result['turns'])<=8
    if scenario=='first_time_A':
        from app.core.config import settings
        from app.modules.sales_crm.models import Lead
        from tools.sales_ai.compact_battery import resources
        forged=[{'reply':t['reply'].replace(settings.PUBLIC_APP_URL,'https://wrong-host.invalid')} for t in result['turns']]
        _,checks=resources(db,manifest,db.get(Lead,result['lead_id']),result['property_type_id'],forged)
        assert any(c['check']=='only_registered_material_urls' and c['status']=='FAIL' for c in checks)


def test_battery_covers_seven_segments_and_unknown_with_eight_booking_goals():
    assert {p['segment'] for p in PERSONAS if p['segment']}==BUYER_SEGMENTS
    assert len(CASES)==16 and sum(s['goal']=='booked' for s in SPECS.values())==8
    assert sum(p['segment'] is None for p in PERSONAS)==1
    assert {s['project'] for s in SPECS.values()}=={0,1,2}
    from tools.sales_ai.compact_battery import unknown_inventory_answered
    assert unknown_inventory_answered('The price is not confirmed. Availability is not confirmed. Your budget is 500,000 USD.')
    assert not unknown_inventory_answered('The price is not confirmed. Last confirmed quantity: 0.')
    assert not unknown_inventory_answered('The price is not confirmed.')


def test_public_selection_uses_only_offered_option_and_requires_prior_selection():
    assert public_next('Please confirm your visit',[],'Bay Residence')==(None,'confirmation_without_selection')
    reply='Verified visit options:\n\n1. 2026-11-14 at 10:00 AM (America/New_York, UTC-0500); Seller A\n\n2. 2026-11-14 at 11:00 AM (America/New_York, UTC-0500); Seller A'
    message,action=public_next(reply,[],'Bay Residence',2)
    assert action=='select' and '11:00 AM' in message and '10:00 AM' not in message
    summary='Please confirm your visit: Bay Residence; 2026-11-14 at 11:00 AM (America/New_York, UTC-0500); Seller A; 45 minutes.'
    history=[{'action':'select','lead_message':message}]
    assert public_next(summary,history,'Bay Residence')==('Yes','confirm')
    assert public_next(summary.replace('11:00 AM','10:00 AM'),history,'Bay Residence')==(None,'confirmation_changed_public_selection')
    assert public_next(summary.replace('Bay Residence','Cedar Loft'),history,'Bay Residence')==(None,'confirmation_changed_public_selection')
    assert public_next(summary,history+[{'action':'clarify_visit'}],'Bay Residence')==(None,'confirmation_without_selection')
    assert public_next(reply.split('\n\n2.')[0],[],'Bay Residence',2)==(None,'preferred_option_not_offered')


@pytest.mark.parametrize('scenario',['move_up_A','relocation_A','first_time_A','relocation_B','portfolio_B'])
def test_sales_membership_and_available_slots_are_distinct(lab,scenario):
    from app.modules.project_team.service import eligible_appointment_assignments
    from app.modules.sales_crm.scheduling import eligible_users_for_slot
    from app.modules.users.project_access import project_ids_for_user
    from app.modules.users.models import User
    db,manifest=lab;clock=datetime.utcnow();roster=team(db,manifest,scenario,clock)
    spec=SPECS[scenario];pid=manifest['projects'][spec['project']]['id'];candidate=roster[0]
    actual={a.user_id for a in eligible_appointment_assignments(db,pid)}
    assert actual==({candidate['id']} if spec['access']!='unassigned' else set())
    start=(clock+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    assert set(eligible_users_for_slot(db,project_id=pid,starts_at=start,duration_minutes=30))==(actual if spec['access']!='no_slots' else set())
    assert len(project_ids_for_user(db,db.get(User,candidate['id'])))=={'all':3,'multi':2,'single':1,'unassigned':0,'no_slots':1}[spec['access']]
    assert all(r['company_id']==manifest['company_id'] for r in roster)


def test_compact_prepare_exports_selected_plan_without_model_or_source_reads(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import postgres
    from app.core.config import settings
    from tools.sales_ai.booking_pilot_worker import run
    engine=create_engine('sqlite:///'+str(tmp_path/'lab.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine,autoflush=False))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    options=tmp_path/'options.json';options.write_text(json.dumps(dict(suite='compact-battery',case_selection=['unknown_A','relocation_B'],credential={},prepare_only=True,max_calls=40,max_turns=8)))
    output=tmp_path/'results';output.mkdir()
    assert run(options,output)==0
    report=json.loads((output/'summary.json').read_text());plan=json.loads((output/'scenario-plan.json').read_text())
    assert report['scenario_count']==2 and report['defined_scenario_count']==16 and not report['is_full_battery']
    assert report['provider_calls']==0 and report['team']==[] and report['expected_bookings']==1
    assert list(plan['scenarios'])==['unknown_A','relocation_B']
    assert (output/'synthetic-sales-results.zip').is_file()
    engine.dispose()


@pytest.mark.parametrize('ids',[['unknown_A','unknown_A'],['not-a-case']])
def test_invalid_case_selection_fails_before_any_source_database_read(monkeypatch,tmp_path,ids):
    from tools.sales_ai import synthetic_lab
    monkeypatch.setattr(synthetic_lab,'configuration',lambda *args:pytest.fail('Source configuration must not be read.'))
    monkeypatch.setattr('sys.argv',['synthetic_lab','--suite','compact-battery','--max-turns','8','--output',str(tmp_path/'out'),'--cases',*ids])
    with pytest.raises(SystemExit) as error:synthetic_lab.main()
    assert error.value.code==2 and not (tmp_path/'out').exists()


def test_full_worker_keeps_failures_visible_and_exports_eight_real_private_bookings(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import postgres
    from app.core.config import settings
    from tools.sales_ai.booking_pilot_worker import run
    engine=create_engine('sqlite:///'+str(tmp_path/'lab.db'))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=engine,autoflush=False))
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path/'uploads'))
    secret='NEVER-EXPORT-COMPACT-KEY'
    options=tmp_path/'options.json';options.write_text(json.dumps(dict(suite='compact-battery',credential=dict(id='config',key=secret,pack={'model':'test/offline'},version_id='published',version_number=1,published_at=None),prepare_only=False,max_calls=320,max_turns=8)))
    output=tmp_path/'results';output.mkdir()
    original=httpx.AsyncClient
    def failing_provider(request):
        ctx=json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'annual rental yield' in ctx['current_message']:
            return httpx.Response(400,json={'error':{'message':'Deliberate offline failure'}})
        return provider(request)
    class FailingClient(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(failing_provider),trust_env=False,**kwargs)
    with patch.object(httpx,'AsyncClient',FailingClient):status=run(options,output)
    report=json.loads((output/'summary.json').read_text())
    assert status==2 and report['status']=='FAIL' and report['is_full_battery']
    assert report['expected_bookings']==report['actual_bookings']==8
    assert [r['case'] for r in report['cases']]==list(CASES)
    assert report['summary']['FAIL']>=1 and report['provider_calls']<=320
    assert report['lead_model'] is report['judge_model'] is None
    assert any(c['case']=='rental_B' and c['status']=='FAIL' for c in report['case_results'])
    assert not report['cost_reporting_complete']
    assert all(c['profile_read_mode']=='new_session_after_commit' for c in report['cases'])
    assert secret not in (output/'summary.json').read_text() and secret not in (output/'report.json').read_text()
    assert (output/'synthetic-sales-results.zip').is_file()
    assert report['production_database_writes']==report['lead_contacts']==0
    engine.dispose()



def test_unregistered_or_unresolvable_public_links_fail_material_audit(lab):
    from app.modules.sales_crm.models import Lead
    from tools.sales_ai.compact_battery import resources
    db,manifest=lab
    lead=Lead(company_id=manifest['company_id'],project_id=manifest['projects'][0]['id'],full_name='Synthetic Link Probe',phone='+15550309999',is_demo=True)
    db.add(lead);db.commit()
    receipts,checks=resources(db,manifest,lead,manifest['projects'][0]['properties'][0]['id'],
        [{'reply':'https://example.invalid/unregistered.pdf https://blackpenguin.ai/api/v1/projects/a/not-a-real-token'}])
    assert not receipts
    assert {'only_registered_material_urls','issued_material_link_resolves_in_private_database','no_unregistered_material_link'}<={c['check'] for c in checks if c['status']=='FAIL'}
