"""Production-observed semantics and crash journal regressions, no paid inference."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from test_sales_compact_battery import provider
from app.modules.sales_agent.interpretation_input import compile_input,legacy,document,Input
from app.modules.sales_agent.interpretation_consistency import normalize
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from tools.sales_ai.compact_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_2_packets.json').read_text())['rows']
CONTEXT={'property_types':[{'property_type':n} for n in ['Bay Residence','Cedar Loft','Cedar Studio','Ridge Townhome','Summit Villa','Valley Apartment']]}

@pytest.mark.parametrize('row',[r for r in ROWS if r['attempts'] and r['action'] in {'request_visit','material','missing_material','decline'}],ids=lambda r:r['case']+'-'+r['action'])
def test_actual_native_packets_preserve_new_visit_and_material_owner(row):
    try:u,_=compile_input(row['attempts'][-1],row['text'])
    except ValueError:pytest.fail('Recorded packet should be structurally valid.')
    result,notes=normalize(u,row['text'],CONTEXT)
    if row['action']=='request_visit':
        assert result.permits('appointment') and result.appointment_query is None and result.visit.action=='request'
    if row['action'] in {'material','missing_material'}:
        request=next(r for r in result.requests if r.topic.value=='materials')
        reference=next(r for r in result.references if r.id==request.reference_id)
        assert reference.kind=='property' and request.subject is not None
    if row['action']=='decline':assert result.cancellation is result.reschedule is None and result.visit.action=='decline'
    assert normalize(result,row['text'],CONTEXT)[0]==result

@pytest.mark.parametrize('text',["My friend said I would like to arrange an in-person visit to Bay Residence.","If I would like to arrange a visit to Bay Residence, what happens?","I do not want to book a visit to Bay Residence.","Can you show my active appointments?"])
def test_no_new_visit_recovered_from_reporting_hypothesis_negation_or_existing_query(text):
    u=understanding(text,'other');result,notes=normalize(u,text,CONTEXT)
    assert result==u and not notes


def test_any_time_is_not_a_required_clock_range_and_never_confirmation():
    text='I would like to arrange an in-person visit to Bay Residence. Any available time in the next seven days works for me.'
    data=understanding(text,'appointment').model_dump();data['appointment_query']='active';data['visit']=dict(action='request',evidence=text,timing=dict(time_relation='range',date_from_evidence='next seven days'))
    u=Understanding.model_validate(data)
    result,notes=normalize(u,text,CONTEXT)
    assert result.visit.action=='request' and result.visit.timing.time_relation=='any' and result.appointment_query is None
    assert not result.permits('opt_out') and result.cancellation is result.reschedule is None

@pytest.mark.parametrize('scenario',CASES)
def test_native_variations_pass_information_material_booking_and_decline_journey(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='consistency-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    actual={r['text']:r for r in ROWS if r['case']==scenario and r['attempts'] and r['action'] in {'request_visit','material','missing_material','decline'}}
    def response(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if payload['response_format']['json_schema']['name']=='sales_understanding' and text in actual:
            # Only existing recorded responses are replayed here. Missing crash
            # packets are not represented as production evidence.
            return httpx.Response(200,json={'choices':[{'message':{'content':actual[text]['attempts'][-1]}}]})
        result=provider(request)
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            data,_=legacy(document(result.json()['choices'][0]['message']['content']),text)
            return httpx.Response(200,json={'choices':[{'message':{'content':Input.model_validate(data).model_dump_json()}}]})
        return result
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kw)
    budget=Budget(40)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    assert not [(t['action'],t.get('reply'),c) for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    assert not [c for c in result['checks'] if c['status']=='FAIL']
    assert len(result['meetings'])==int(scenario.endswith('_A'))

@pytest.mark.parametrize('phase',['repair','planning'])
def test_crash_outside_model_validation_keeps_attempts_locations_and_literal_facts(lab,phase):
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.models import SalesConversation,AgentRun,OutboundMessage
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.lead_profile import resolve
    from app.modules.sales_agent.profile_intelligence import budget_cap
    db,manifest=lab;project=manifest['projects'][0]
    db.add(AIConfiguration(id='crash-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}))
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Synthetic Crash',phone='+15550101919',is_demo=True,consent_status='granted_simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH');db.add(lead);db.flush()
    db.add(SalesConversation(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(provider if phase=='planning' else lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'{"broken":true}'}}]})),trust_env=False,**kw)
    target='app.modules.sales_agent.understanding_repair.constrained_repair_schema' if phase=='repair' else 'app.modules.sales_agent.turn_planner.run'
    text='I am buying my first home. My budget is 900,000 USD, paying cash. What can you tell me about Bay Residence?'
    with patch.object(httpx,'AsyncClient',Client),guard(Budget(10)),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None),patch(target,side_effect=TypeError('SENSITIVE exception body must not be exported')):
        asyncio.run(turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=text,event_id='crash-event'));db.commit()
    run=db.query(AgentRun).filter_by(event_id='crash-event').one()
    assert run.error_code=='TypeError'
    diagnostic=run.output_snapshot['error_diagnostic'];assert diagnostic['frames']
    assert 'SENSITIVE' not in json.dumps(diagnostic)
    audit=run.input_snapshot['interpretation_failure'];assert audit['interpretation_attempts']
    if phase=='repair':assert audit['pending_raw_response']
    assert budget_cap(resolve(lead))==(900000,'USD')
    assert db.query(Meeting).count()==db.query(OutboundMessage).count()==0


@pytest.mark.parametrize('text',[
    'I would like to arrange a visit to Cedar Loft or Cedar Studio.',
    'I do not want a visit yet. I would like to arrange a visit to Cedar Loft.',
])
def test_multiple_owners_or_conflicting_visit_intent_are_not_recovered(text):
    value=understanding(text,'other')
    result,notes=normalize(value,text,CONTEXT)
    assert result==value and not notes
