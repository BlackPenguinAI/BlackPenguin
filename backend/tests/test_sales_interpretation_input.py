"""Typed wire input, real failed attempt sequences, and isolated fact persistence."""
import asyncio,copy,json
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from test_sales_compact_battery import provider
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.interpretation_input import Input,compile_input,schema,VERSION
from app.modules.sales_agent.current_declarations import extract
from tools.sales_ai.compact_battery import evaluate_case,CASES
from tools.sales_ai.evaluation_guard import Budget,guard

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_1_attempts.json').read_text())['rows']
PACKETS=[(r,a) for r in ROWS if r['failed'] for a in r['attempts']]


def packet():
    data=understanding('Hello','other').model_dump(mode='json')
    for k in ['all_of','references','selected_reference_id','comparison']:data.pop(k)
    data.update(version=VERSION,requests=[],alternatives=[],constraints=[],selection=None)
    return data


def test_wire_schema_makes_document_tags_and_external_reference_ids_impossible():
    data=packet();data['requests']=[dict(topic='inventory',subject='unit_sheet',polarity='request',evidence='Show me Studio.',target=None)]
    with pytest.raises(ValueError):Input.model_validate(data)
    data['requests'][0]['subject']=None;data['requests'][0]['reference_id']='ref1'
    with pytest.raises(ValueError):Input.model_validate(data)
    del data['requests'][0]['reference_id']
    data['requests'][0]['target']=dict(kind='property',expression='Studio',evidence='Studio',id='db-uuid')
    with pytest.raises(ValueError):Input.model_validate(data)
    doc=schema('Show me Studio.')
    assert doc['additionalProperties'] is False and 'references' not in doc['properties']
    assert all('id' not in v.get('properties',{}) for k,v in doc['$defs'].items() if k.endswith('Request') or k.endswith('Target'))


def test_inline_subjects_comparisons_and_or_groups_get_backend_owned_links():
    text='Send Studio photos or its brochure. Compare Studio and Loft.'
    data=packet();target=dict(kind='property',expression='Studio',evidence='Studio')
    data['alternatives']=[dict(evidence='Send Studio photos or its brochure.',requests=[dict(topic='materials',subject=s,polarity='request',evidence='Send Studio photos or its brochure.',target=target) for s in ['photos','brochure']])]
    data['requests']=[dict(topic='comparison',polarity='request',evidence='Compare Studio and Loft.',members=[target,dict(kind='property',expression='Loft',evidence='Loft')],criteria=['general'],include_current=False,include_all=False,all_kind='property',feature=None,operation='compare')]
    result,notes=compile_input(json.dumps(data),text)
    assert result.comparison.request_id=='r0' and result.comparison.reference_ids==['ref0','ref1']
    assert result.alternatives[0].request_ids==['r1','r2'] and result.all_of==['r0']
    assert [r.reference_id for r in result.requests[1:]]==['ref0','ref0']
    assert result.visit is result.cancellation is result.reschedule is None


@pytest.mark.parametrize('row,raw',PACKETS,ids=[r['case']+'-'+r['action']+'-'+str(i) for i,(r,a) in enumerate(PACKETS)])
def test_both_real_failed_attempts_preserve_only_current_quotations(row,raw):
    prefs=extract(row['text'],raw)
    assert all(p.evidence in row['text'] for p in prefs)
    if row['action'] in {'request_visit','missing_material','switch','unknown_inventory'}:
        assert not any(p.key in {'budget','financing'} for p in prefs)
    try:value,notes=compile_input(raw,row['text'])
    except ValueError:return # Ambiguous/contradictory packets remain rejected; facts survive separately.
    assert all(p.evidence in row['text'] for p in value.preferences)
    assert all(r.id.startswith('ref') for r in value.references)


@pytest.mark.parametrize('text',["My friend said my budget is 300,000 USD, paying cash.","If my budget is 300,000 USD, can I pay cash?","I cannot pay cash.","My budget is 100,000 USD or 300,000 USD."])
def test_literal_profile_capture_never_invents_own_funds(text):
    assert not extract(text)


@pytest.mark.parametrize('scenario',tuple(dict.fromkeys(r['case'] for r in ROWS)))
def test_replay_real_attempts_without_an_idealized_second_response(lab,scenario,tmp_path):
    db,manifest=lab
    db.add(AIConfiguration(id='wire-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    rows={r['text']:r for r in ROWS if r['case']==scenario};seen={}
    def response(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if payload['response_format']['json_schema']['name']=='sales_understanding' and text in rows:
            index=seen.get(text,0);seen[text]=index+1
            attempts=rows[text]['attempts']
            # On an exhausted sequence return its LAST ACTUAL failed packet.
            # Never replace repair with the offline ideal provider.
            raw=attempts[min(index,len(attempts)-1)]
            return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
        return provider(request)
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kwargs)
    budget=Budget(40)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    from tools.sales_ai.evaluation_checks import sanitize
    (tmp_path/'replay-result.json').write_text(json.dumps(sanitize(result),default=str))
    # Endpoint outcomes are audited, not forced successful when captured semantic
    # ambiguity remains. No unintended booking or lost explicit money is allowed.
    assert len(result['meetings'])<=int(scenario.endswith('_A'))
    for t in result['turns']:
        assert all(c['status']=='PASS' for c in t['checks'] if c['check'] in {'declared_budget_persists','cash_preference_persists','no_booking_without_confirmation','at_most_one_booking'}),(scenario,t['action'],t['checks'])
    assert all(c['status']=='PASS' for c in result['checks'] if c['check'] in {'no_provider_outbox','eligible_roster_matches_assignments'})


@pytest.mark.parametrize('failure',['malformed','http400','manual_pause'])
def test_unusable_requests_still_capture_valid_declarations_without_actions(lab,failure):
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesConversation,OutboundMessage
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.lead_profile import resolve
    from app.modules.sales_agent.profile_intelligence import budget_cap,segment_for
    db,manifest=lab;project=manifest['projects'][0]
    db.add(AIConfiguration(id='fail-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}))
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Synthetic Failed Request',phone='+15550999999',is_demo=True,is_test=True,platform='evaluation',consent_status='granted_simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH',preferred_channel='simulation')
    db.add(lead);db.flush();db.add(SalesConversation(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False));db.commit()
    def failed_response(request):
        if failure=='manual_pause':
            conversation=db.query(SalesConversation).filter_by(lead_id=lead.id).one();conversation.is_paused=True;conversation.pause_reason='Manual control';db.commit()
        return httpx.Response(400,json={'error':{'message':'Offline injected failure'}}) if failure=='http400' else httpx.Response(200,json={'choices':[{'message':{'content':'{"broken":true}'}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(failed_response),trust_env=False,**kwargs)
    text='I am buying my first home. My budget is 900,000 USD, paying cash. Show me Bay Residence.'
    with patch.object(httpx,'AsyncClient',Client),guard(Budget(4)),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        asyncio.run(turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=text,event_id='broken-request'));db.commit()
        if failure=='manual_pause':
            assert budget_cap(resolve(lead)) is None and not db.query(Meeting).count()
            assert db.query(SalesConversation).filter_by(lead_id=lead.id).one().is_paused
            return
        assert budget_cap(resolve(lead))==(900000,'USD') and segment_for(lead)=='first_time_buyer'
        before=copy.deepcopy(lead.lead_profile_data)
        asyncio.run(turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=text,event_id='broken-request'));db.commit()
        assert lead.lead_profile_data==before
    assert db.query(Meeting).count()==db.query(OutboundMessage).count()==0


@pytest.mark.parametrize('scenario',CASES)
def test_native_wire_contract_reaches_actual_core_without_legacy_packet_shape(lab,scenario):
    from app.modules.sales_agent.interpretation_input import legacy,document
    db,manifest=lab
    db.add(AIConfiguration(id='native-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    def response(request):
        payload=json.loads(request.content);result=provider(request)
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            ctx=json.loads(payload['messages'][1]['content']);raw=result.json()['choices'][0]['message']['content']
            data,_=legacy(document(raw),ctx['current_message']);data=Input.model_validate(data).model_dump(mode='json')
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]})
        return result
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kwargs)
    budget=Budget(30)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    assert not [c for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    assert not [c for c in result['checks'] if c['status']=='FAIL']
    assert len(result['meetings'])==int(scenario.endswith('_A'))


def test_schema_probe_requires_native_wire_output_and_makes_one_network_call(monkeypatch):
    from tools.sales_ai.probe_interpretation import probe
    def response(request):
        data=json.loads(request.content);sample=json.loads(data['messages'][1]['content'])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(sample)}}]})
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kwargs)
    with patch.object(httpx,'AsyncClient',Client):result=asyncio.run(probe('OFFLINE','test/offline'))
    assert result['result']=='accepted' and result['provider_calls']==1


def test_bad_model_normalization_cannot_override_third_party_or_ambiguous_quotes():
    samples=[('My friend said I am buying my first home.',dict(key='buyer_type',value='first_time_buyer',evidence='I am buying my first home.')),
             ('My budget is 100,000 USD or 300,000 USD.',dict(key='budget',value='100000 USD',evidence='My budget is 100,000 USD')),
             ('I can pay cash or use a mortgage.',dict(key='financing',value='cash',evidence='I can pay cash'))]
    for text,pref in samples:
        data=understanding(text,'other').model_dump(mode='json');data['preferences']=[dict(status='declared',**pref)]
        assert not extract(text,json.dumps(data))
