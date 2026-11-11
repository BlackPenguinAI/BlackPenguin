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

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_4_packets.json').read_text())['rows']
@pytest.mark.parametrize('scenario',['first_time_A','move_up_B','unknown_A'])
def test_repair4_recorded_interpretations_preserve_scope_and_finish_journeys(lab,scenario):
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


def test_catalog_permutation_restored_without_changing_wordings_or_continuation():
    from app.modules.sales_agent.commercial_composer import Composition,validate_ordered,CompositionViolation,VERSION
    blocks=[{'id':'e0','required':True,'wordings':{'direct':'Here are options'}},{'id':'e1','required':True,'wordings':{'direct':'1. Studio'}},{'id':'e2','required':True,'wordings':{'direct':'2. Loft'}}]
    plan=Composition(version=VERSION,opening='direct',continuation_id='none',blocks=[dict(evidence_id=i,wording='direct') for i in ['e0','e2','e1']],paragraphs=[['e0'],['e2','e1']])
    result,notes=validate_ordered(plan,blocks,[{'id':'none'}])
    assert [b.evidence_id for b in result.blocks]==['e0','e1','e2'] and result.paragraphs==[['e0'],['e1','e2']]
    assert result.continuation_id==plan.continuation_id and notes[0]['rule_code']=='catalog_order'
    assert all(b.wording=='direct' for b in result.blocks)
    for bad in [plan.model_copy(update={'paragraphs':[['e0']]}),plan.model_copy(update={'blocks':plan.blocks[:2]}),plan.model_copy(update={'continuation_id':'forged'})]:
        with pytest.raises(CompositionViolation):validate_ordered(bad,blocks,[{'id':'none'}])


def test_pure_order_error_does_not_spend_a_second_model_call(monkeypatch):
    from app.modules.sales_agent import commercial_composer as composer
    from test_sales_composer_http import compose
    blocks=composer.evidence_blocks('1. Studio\n\n2. Loft')
    monkeypatch.setattr(composer,'evidence_blocks',lambda text:blocks)
    calls=[]
    async def infer(model,messages,schema):
        calls.append(model)
        return json.dumps(dict(version=composer.VERSION,opening='direct',blocks=[dict(evidence_id=k,wording='direct') for k in ['e1','e0']],continuation_id='none',paragraphs=[['e1'],['e0']]))
    draft=compose(monkeypatch,infer)
    assert len(calls)==1 and draft.trace['status']=='accepted'
    assert draft.text.index('1. Studio')<draft.text.index('2. Loft')
    assert draft.trace['attempts'][0]['normalizations'][0]['rule_code']=='catalog_order'
