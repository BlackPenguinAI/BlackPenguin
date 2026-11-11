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

ROWS=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_repair_6_packets.json').read_text())['rows']
@pytest.mark.parametrize('scenario',['first_time_A','move_up_B','unknown_A'])
def test_repair6_recorded_dialogues_do_not_replay_history_or_recompose_receipts(lab,scenario):
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



    if scenario.endswith('_A'):
        final=result['turns'][-1]
        assert final['action']=='confirm'
        assert final['output']['metadata']['composition']['status']=='backend_rendered'
        assert final['output']['metadata']['composition']['attempts']==[]
    if scenario=='first_time_A':
        assert len(result['turns'])==5  # request advances immediately, no repeated lead turn
        visit=next(t for t in result['turns'] if t['action']=='request_visit')
        assert len(visit['interpretation_attempts'])==1
        assert len([n for n in visit['interpretation_attempts'][0]['normalizations'] if n['action']=='omit_verified_historical_request'])==2
    if scenario=='move_up_B':
        first=result['turns'][0]
        assert 'Cedar Studio' in first['reply'] and 'Cedar Loft' not in first['reply']
        assert first['input_trace']['understanding']['visit'] is None
        assert len(result['turns'][1]['interpretation_attempts'])==1
        assert result['turns'][1]['input_trace']['understanding']['confidence']==1.0




HISTORICAL=[row['text'] for row in ROWS if row['case']=='first_time_A'][:2]
VISIT=next(row for row in ROWS if row['case']=='first_time_A' and 'I would like to arrange' in row['text'] and row['attempts'])

def test_history_omission_requires_actual_history_and_preserves_current_evidence():
    from app.modules.sales_agent.understanding_contract import parse
    text=VISIT['text'];raw=VISIT['attempts'][0]
    with pytest.raises((ValueError,TypeError)):parse(compile_input(raw,text)[0].model_dump_json(),text)
    value,notes=compile_input(raw,text,historical_messages=HISTORICAL)
    parse(value.model_dump_json(),text)
    assert not value.requests and value.visit.action=='request'
    assert value.confidence==1 and len([n for n in notes if n['action']=='omit_verified_historical_request'])==2
    data=json.loads(raw)
    data['requests'].append({'topic':'location','polarity':'request','evidence':"Please use the project timezone.",'target':None,'subject':None})
    value,notes=compile_input(json.dumps(data),text,historical_messages=HISTORICAL)
    assert len(value.requests)==1 and value.requests[0].topic.value=='location'

@pytest.mark.parametrize('change',['exclude','alternative','unknown','no_visit','uncertain','negative','opt_out','human','appointment','repeated_mixed_request'])
def test_invalid_or_restrictive_evidence_is_not_silently_removed(change):
    data=json.loads(VISIT['attempts'][0]);text=VISIT['text']
    if change=='repeated_mixed_request':text+=' Also send the same PDF again.'
    elif change in {'opt_out','human','appointment'}:
        data['requests'][0].update(topic=change,subject=None);data['requests'][0].pop('detail_fields',None);data['requests'][0].pop('feature',None)
    elif change=='exclude':data['requests'][0]['polarity']='exclude'
    elif change=='alternative':data['alternatives']=[{'requests':list(data['requests']),'evidence':HISTORICAL[0]}];data['requests']=[]
    elif change=='unknown':data['requests'][0]['evidence']='Unknown previous request not in conversation'
    elif change=='no_visit':data['visit']=None
    elif change=='uncertain':data.update(requires_clarification=True,clarification_question='Which visit?')
    elif change=='negative':text='I do not want to arrange an in-person visit to Cedar Studio.';data['visit']['evidence']=text
    value,_=compile_input(json.dumps(data),text,historical_messages=HISTORICAL)
    from app.modules.sales_agent.understanding_contract import parse
    with pytest.raises((ValueError,TypeError)):parse(value.model_dump_json(),text)

@pytest.mark.parametrize('mode',['receipt','no_record','extra_question','mixed_evidence','unverified_text'])
def test_deterministic_receipt_is_narrow_and_does_not_mask_provider_failure(monkeypatch,mode):
    from types import SimpleNamespace as NS
    from app.modules.sales_agent import commercial_composer as c,turn_memory
    from app.modules.sales_agent.understanding_contract import DialogueState
    from app.modules.sales_crm.models import Lead
    monkeypatch.setattr(c,'resolve',lambda *a:{'model':'test/offline','source':{},'selection':{}})
    monkeypatch.setattr(turn_memory,'build',lambda *a,**kw:{'appointments':{'active':{'count':1}}})
    choices=[{'id':'none','text':'','metadata':{}}]
    if mode=='extra_question':choices=[{'id':'clarify','text':'Which property?','metadata':{}}]
    monkeypatch.setattr(c,'select_continuations',lambda **kw:choices)
    calls=[]
    async def timeout(*a):calls.append(1);raise TimeoutError()
    meta={'meeting_id':'recorded','booking_operation_id':'committed'}
    if mode=='no_record':meta.pop('booking_operation_id')
    text='Your visit is confirmed: Cedar Studio; a verified time and location.'
    extra=[text]
    if mode=='mixed_evidence':extra.append('Approved payment options: cash.')
    draft=text if mode=='unverified_text' else ''
    if mode=='unverified_text':extra=[]
    out=asyncio.run(c.compose(None,None,inbound=NS(id='synthetic',content='Yes'),
        outcome=NS(state=DialogueState(last_understanding=understanding('Yes','appointment')),results=[],plan={}),
        draft=NS(text=draft),commercial={'confirmed_project_facts':{},'property_types':[]},
        lead=Lead(meta_form_data={},lead_profile_data={}),metadata=meta,previous_meta={},holds=[],channel='whatsapp',extra=extra,infer=timeout))
    if mode=='receipt':
        assert not calls and out.trace['status']=='backend_rendered' and out.text==text
        assert out.trace['attempts']==[] and out.trace['external_actions']==0
    else:
        assert calls==[1] and out.trace['status']=='safe_fallback'
        assert out.trace['attempts'][0]['error_code']=='TimeoutError'
