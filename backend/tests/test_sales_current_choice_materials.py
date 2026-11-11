"""Production-observed semantics and crash journal regressions, no paid inference."""
import asyncio,json
from datetime import datetime
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

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_5_packets.json').read_text())['rows']
@pytest.mark.parametrize('scenario',['first_time_A','move_up_B','unknown_A'])
def test_repair5_recorded_dialogues_deliver_switch_material_and_preserve_visits(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='consistency-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    actual={}
    for row in ROWS:
        if row['case']==scenario and row['attempts']:actual.setdefault(row['text'],[]).extend(row['attempts'])
    replayed=[]
    def response(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if payload['response_format']['json_schema']['name']=='sales_understanding' and text=='Show me all property types.':
            data,_=legacy(document(understanding(text,'catalog').model_dump_json()),text)
            return httpx.Response(200,json={'choices':[{'message':{'content':Input.model_validate(data).model_dump_json()}}]})
        if payload['response_format']['json_schema']['name']=='sales_understanding' and text in actual:
            # Only existing recorded responses are replayed here. Missing crash
            # packets are not represented as production evidence.
            raw=actual[text].pop(0) if len(actual[text])>1 else actual[text][0]
            replayed.append(text)
            return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
        result=provider(request)
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            data,_=legacy(document(result.json()['choices'][0]['message']['content']),text)
            return httpx.Response(200,json={'choices':[{'message':{'content':Input.model_validate(data).model_dump_json()}}]})
        return result
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kw)
    class Frozen(datetime):
        @classmethod
        def utcnow(cls):return cls(2026,11,11,6,34)
    budget=Budget(40)
    with patch('tools.sales_ai.compact_battery.datetime',Frozen),patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
        if scenario=='move_up_B':
            from app.modules.sales_agent.current_simulation import turn
            from app.modules.sales_agent.models import AgentRun
            asyncio.run(turn(db,company_id=manifest['company_id'],lead_id=result['lead_id'],inbound_text='Show me all property types.',event_id='broad-after-selected'))
            run=db.query(AgentRun).filter_by(event_id='broad-after-selected').one()
            assert 'Cedar Loft' in run.output_snapshot['reply'] and 'Cedar Studio' in run.output_snapshot['reply']

    assert not [(t['action'],t.get('reply'),c) for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    assert not [c for c in result['checks'] if c['status']=='FAIL']
    assert len(result['meetings'])==int(scenario.endswith('_A'))
    if scenario.endswith('_A'):
        assert sum('I would like the first appointment:' in text for text in replayed)>=1  # invalid first attempt plus recorded repair
    if scenario=='first_time_A':assert 'Please send the brochure PDF for Cedar Studio.' in replayed



    if scenario=='move_up_B':
        first=result['turns'][0]
        assert 'Cedar Studio' in first['reply'] and 'Cedar Loft' not in first['reply']
        assert first['input_trace']['understanding']['visit'] is None
        assert len(result['turns'][1]['interpretation_attempts'])==1
        assert result['turns'][1]['input_trace']['understanding']['confidence']==1.0



CONTEXT={'property_types':[{'property_type':'Cedar Loft'},{'property_type':'Cedar Studio'}]}

def bad_switch(text,confidence=1.0):
    data=understanding(text,'materials').model_dump()
    row=data['requests'][0];row.update(subject='photos',reference_id='bad')
    data['references']=[dict(id='bad',kind='material',expression='Cedar Loft',evidence=text)]
    data['confidence']=confidence
    data['visit']=dict(action='request',evidence=text,timing=None)
    return Understanding.model_validate(data)

@pytest.mark.parametrize('text',[
    'Actually I prefer Cedar Loft instead. Please send its photos.',
    'Actually, I choose Cedar Loft instead. Could you send me its pictures?',
    "I'd like Cedar Loft. Show me that property's images.",
    "I'll take Cedar Loft. Can you show its photos?",
])
def test_explicit_current_choice_owns_following_material_request_without_visit(text):
    value=bad_switch(text);result,notes=normalize(value,text,CONTEXT)
    assert result.visit is None and result.confidence==value.confidence
    assert result.selected_reference_id==result.requests[0].reference_id
    ref=next(r for r in result.references if r.id==result.selected_reference_id)
    assert ref.kind=='property' and ref.expression=='Cedar Loft'
    assert result.requests[0].subject=='photos' and result.permits('materials','photos')
    assert not result.permits('appointment') and not result.permits('opt_out')
    assert notes and normalize(result,text,CONTEXT)[0]==result

@pytest.mark.parametrize('text',[
    'I do not prefer Cedar Loft. Please send its photos.',
    'If I prefer Cedar Loft instead. Please send its photos.',
    'My friend said I prefer Cedar Loft instead. Please send its photos.',
    'Actually I prefer Cedar Loft or Cedar Studio instead. Please send its photos.',
    'Actually I prefer Cedar Loft from another company instead. Please send its photos.',
    'Please send its photos.',
    'Actually I prefer Cedar Loft instead. Do not send its photos.',
    'Actually I prefer Cedar Loft instead. Please send its photos and reserve it.',
])
def test_ambiguous_reported_negative_or_mixed_choice_is_not_recovered(text):
    value=bad_switch(text);result,notes=normalize(value,text,CONTEXT)
    assert result.selected_reference_id is None
    assert not any(n['action']=='bind_anaphoric_material_to_explicit_current_choice' for n in notes)

def test_low_confidence_and_existing_restrictions_are_not_promoted_or_removed():
    text='Actually I prefer Cedar Loft instead. Please send its photos.'
    value=bad_switch(text,0.0);result,_=normalize(value,text,CONTEXT)
    assert result.confidence==0.0
    data=value.model_dump();data['constraints']=[dict(topic='materials',subject='photos',effect='prohibit',scope='until_explicit_change',evidence=text,reference_id='bad')]
    value=Understanding.model_validate(data);result,notes=normalize(value,text,CONTEXT)
    assert result.constraints==value.constraints and result.selected_reference_id is None
    duplicate={'property_types':[{'property_type':'Cedar Loft'},{'property_type':'Cedar Loft'}]}
    result,notes=normalize(bad_switch(text),text,duplicate)
    assert result.selected_reference_id is None

def test_scope_check_accepts_details_and_catalog_but_not_wrong_or_missing_subject():
    from tools.sales_ai.compact_battery import named_property_answered
    expected={'id':'studio','name':'Cedar Studio'};other={'id':'loft','name':'Cedar Loft'}
    details={'selected_property_type_id':'studio','planning':{'references':{'r':{'status':'resolved','value':{'property_id':'studio'}}}}}
    assert named_property_answered('Cedar Studio has one bedroom.',details,expected,[expected,other])
    assert named_property_answered('Cedar Studio has one bedroom.',{'property_catalog_offer':{'property_type_ids':['studio']}},expected,[expected,other])
    assert not named_property_answered('Cedar Studio and Cedar Loft',details,expected,[expected,other])
    assert not named_property_answered('Which one?',details,expected,[expected,other])
    assert not named_property_answered('Cedar Studio',{},expected,[expected,other])
    assert not named_property_answered('Cedar Studio',{'property_catalog_offer':{'property_type_ids':['loft']}},expected,[expected,other])
