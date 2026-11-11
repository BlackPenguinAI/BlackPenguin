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

@pytest.fixture(autouse=True)
def seeded_inventory_clock(monkeypatch):
    # The replay clock must not precede the synthetic inventory verification.
    from tools.sales_ai import synthetic_fixtures
    class SeedClock(datetime):
        @classmethod
        def utcnow(cls):return cls(2026,11,11,6,0)
    monkeypatch.setattr(synthetic_fixtures,'datetime',SeedClock)

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_battery_2_packets.json').read_text())['rows']
@pytest.mark.parametrize('scenario',['move_up_A','downsizing_B','portfolio_A'])
def test_battery2_failed_cases_complete_without_retrying_the_lead(lab,scenario):
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

    assert not [(t['action'],t.get('reply'),c) for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    assert not [c for c in result['checks'] if c['status']=='FAIL'], [(t['action'],t['reply']) for t in result['turns']]
    assert len(result['meetings'])==int(scenario.endswith('_A'))
    if scenario=='move_up_A':assert len(result['turns'])==5
    if scenario=='downsizing_B':
        row=next(t for t in result['turns'] if t['action']=='missing_material')
        assert len(row['interpretation_attempts'])==1
        assert row['input_trace']['understanding']['confidence']==1
        assert 'clarify' not in row['reply'].lower()
    if scenario=='portfolio_A':
        visit=next(t for t in result['turns'] if t['action']=='request_visit')
        timing=visit['input_trace']['understanding']['visit']['timing']
        assert timing['time_relation']=='any'
        assert timing['time_from_evidence'] is None and timing['time_until_evidence'] is None
        assert not any(t['action']=='clarify_visit' for t in result['turns'])


@pytest.mark.parametrize('key',['property','visit_readiness'])
def test_only_verified_historical_declarations_can_be_omitted(key):
    from app.modules.sales_agent.understanding_contract import parse
    text='Please send the photos for Ridge Townhome.'
    raw=next(r['attempts'][0] for r in ROWS if r['case']=='downsizing_B' and r['text']==text)
    data=json.loads(raw);data['preferences']=[dict(key=key,value='Ridge Townhome',status='declared',evidence='Show me Ridge Townhome.')]
    value,notes=compile_input(json.dumps(data),text,historical_messages=['Show me Ridge Townhome.'])
    parse(value.model_dump_json(),text)
    assert not value.preferences and value.confidence==1
    assert any(n['action']=='omit_verified_historical_optional_preference' for n in notes)
    for history,status in [([], 'declared'),(['Show me Ridge Townhome.'],'declined')]:
        data['preferences'][0]['status']=status
        value,_=compile_input(json.dumps(data),text,historical_messages=history)
        with pytest.raises(ValueError):parse(value.model_dump_json(),text)
    data['preferences'][0].update(evidence='Ridge Townhome',status='declared')
    value,_=compile_input(json.dumps(data),text,historical_messages=['Show me Ridge Townhome.'])
    assert len(value.preferences)==1

@pytest.mark.parametrize('modifier',['none','clock','restricted','exact','no_any','unknown_date'])
def test_flexible_date_evidence_is_not_converted_to_clock_or_consent(modifier):
    from app.modules.sales_agent.understanding_contract import Understanding
    from app.modules.sales_agent.interpretation_consistency import normalize
    from test_sales_active_integration import understanding
    text='I would like to arrange an in-person visit to Cedar Loft. Any available time in the next seven days works for me. Please use the project timezone.'
    data=understanding(text,'appointment').model_dump()
    timing=dict(date_from_evidence='next seven days',date_until_evidence='next seven days',time_from_evidence='next seven days',time_until_evidence='next seven days',time_relation='any',timezone_evidence='project timezone',duration_evidence=None)
    if modifier=='clock':text+=' I prefer 3 PM.';timing['time_from_evidence']='3 PM'
    if modifier=='restricted':text+=' Not before 3 PM.'
    if modifier=='exact':timing['time_relation']='exact'
    if modifier=='no_any':text=text.replace('Any available time','A date')
    if modifier=='unknown_date':text=text.replace('next seven days','next month');timing={k:('next month' if v=='next seven days' else v) for k,v in timing.items()}
    data['visit']=dict(action='request',evidence=text,timing=timing)
    data['requests'][0]['evidence']=text
    value=Understanding.model_validate(data)
    result,notes=normalize(value,text,{'property_types':[{'property_type':'Cedar Loft'}]})
    if modifier=='none':
        assert result.visit.timing.time_from_evidence is None and result.visit.timing.time_until_evidence is None
        assert len([n for n in notes if n['action']=='omit_date_phrase_from_flexible_clock'])==2
    else:assert result.visit.timing.time_from_evidence==timing['time_from_evidence']
    assert result.confidence==value.confidence and result.visit.action=='request'
