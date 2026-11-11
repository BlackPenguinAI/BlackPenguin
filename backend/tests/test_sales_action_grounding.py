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

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_3_packets.json').read_text())['rows']
@pytest.mark.parametrize('scenario',['first_time_A','move_up_B','unknown_A'])
def test_recorded_server_attempt_sequences_reach_material_and_booking_outcomes(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='consistency-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    actual={}
    for row in ROWS:
        if row['case']==scenario and row['attempts']:actual.setdefault(row['text'],[]).extend(row['attempts'])
    replayed=[]
    def response(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
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
    with patch('tools.sales_ai.compact_battery.datetime',Frozen),patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    assert not [(t['action'],t.get('reply'),c) for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    assert not [c for c in result['checks'] if c['status']=='FAIL']
    assert len(result['meetings'])==int(scenario.endswith('_A'))
    if scenario.endswith('_A'):
        assert sum('I would like the first appointment:' in text for text in replayed)>=2  # invalid first attempt plus recorded repair
    if scenario=='first_time_A':assert 'Please send the brochure PDF for Cedar Studio.' in replayed



def test_comparative_meaning_and_material_visit_consent_are_checked():
    from app.modules.sales_agent.understanding_semantics import issues_for
    for row in ROWS:
        if row['action'] not in {'material','request_visit','select'}:continue
        for raw in row['attempts']:
            try:value,_=compile_input(raw,row['text'])
            except ValueError:continue
            if value.comparison:
                assert any(i['type']=='comparison_not_supported_by_action' for i in issues_for(value,row['text']))
    text='Compare Cedar Loft and Cedar Studio.'
    value=understanding(text,'catalog').model_dump()
    key=value['requests'][0]['id']
    value['references']=[dict(id='a',kind='property',expression='Cedar Loft',evidence='Cedar Loft'),dict(id='b',kind='property',expression='Cedar Studio',evidence='Cedar Studio')]
    value['comparison']=dict(request_id=key,reference_ids=['a','b'],criteria=['general'],evidence=text)
    assert not any(i['type']=='comparison_not_supported_by_action' for i in issues_for(Understanding.model_validate(value),text))


@pytest.mark.parametrize('text',[
    'Do not send the PDF for Cedar Studio.',
    'My friend said: Please send the PDF for Cedar Studio.',
    'If I ask you to send the PDF for Cedar Studio, what happens?',
    'Please send the PDF for Cedar Loft or Cedar Studio.',
    'I would like the first appointment: a time that was never offered.',
])
def test_material_or_selection_recovery_does_not_invent_unstated_scope_or_offer(text):
    value=understanding(text,'other')
    context={'property_types':[{'property_type':n} for n in ['Cedar Loft','Cedar Studio']]}
    result,notes=normalize(value,text,context)
    assert result==value and not notes


def test_mixed_explicit_visit_and_comparison_remains_a_comparison():
    text='I would like to arrange a visit to Cedar Studio and compare it with Cedar Loft.'
    data=understanding(text,'catalog').model_dump()
    key=data['requests'][0]['id']
    data['references']=[dict(id='a',kind='property',expression='Cedar Studio',evidence='Cedar Studio'),dict(id='b',kind='property',expression='Cedar Loft',evidence='Cedar Loft')]
    data['comparison']=dict(request_id=key,reference_ids=['a','b'],criteria=['general'],evidence=text)
    original=Understanding.model_validate(data)
    result,_=normalize(original,text,{'property_types':[{'property_type':'Cedar Studio'},{'property_type':'Cedar Loft'}]})
    assert result.comparison==original.comparison
