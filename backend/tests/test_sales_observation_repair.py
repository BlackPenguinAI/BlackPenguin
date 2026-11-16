"""Server interpretations plus variants: no paid inference or quality claim."""
import asyncio,json,re
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
import pytest,httpx
from test_sales_booking_pilot import lab
from test_sales_observation_loop import provider as base_provider,prepared
from test_sales_active_integration import understanding
from tools.sales_ai.observation_battery import evaluate_case,CASES
from tools.sales_ai.evaluation_guard import Budget,guard
from app.modules.sales_agent.coordinator_graph import experiment
from app.modules.sales_agent.understanding_contract import Understanding

RECORDS=json.loads(Path(__file__).with_name('fixtures').joinpath('sales_observation_repair/server_frames.json').read_text())


def recorded_provider(recording,scenario):
    case=next(c for c in RECORDS['recordings'][recording] if c['case']==scenario)
    def provider(request):
        p=json.loads(request.content);name=p['response_format']['json_schema']['name']
        if name!='sales_understanding':return base_provider(request)
        text=json.loads(p['messages'][1]['content'])['current_message']
        row=next((t for t in case['turns'] if t['lead_message']==text and t['understanding']),None)
        if row is None:return base_provider(request)
        accepted=[a for a in row['interpretation_attempts'] or [] if a.get('outcome')=='accepted' and a.get('raw_response')]
        raw=accepted[-1]['raw_response'] if accepted else json.dumps(row['understanding'])
        return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
    return provider


@pytest.mark.parametrize('scenario',CASES)
@pytest.mark.parametrize('recording',['reference','candidate'])
@pytest.mark.parametrize('mode',['graph-observe'])
def test_recorded_server_interpretations_complete_short_journeys(lab,scenario,recording,mode,tmp_path):
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    db,manifest=lab
    db.add(AIConfiguration(id='repair-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(recorded_provider(recording,scenario)),trust_env=False,**kw)
    budget=Budget(120)
    with experiment(mode),guard(budget),patch.object(httpx,'AsyncClient',Client),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    (tmp_path/'result.json').write_text(json.dumps({'recording':recording,'autoflush':db.autoflush,**result},indent=2,ensure_ascii=False,default=str))
    bad=[c for t in result['turns'] for c in t['checks'] if c['status']!='PASS']+[c for c in result['checks'] if c['status']!='PASS']
    assert not bad,bad


def malformed_mixed(text,left='photos',right='brochure'):
    return Understanding.model_validate(dict(version='sales-understanding/1.0',requests=[dict(id='a',topic='materials',subject=None,polarity='request',evidence=text,reference_id='fa'),dict(id='b',topic='materials',subject=None,polarity='request',evidence=text,reference_id='fb'),dict(id='c',topic='financing',polarity='request',evidence=text,reference_id='fc')],all_of=['a','b','c'],references=[dict(id='fa',kind='material',expression=left,evidence=text),dict(id='fb',kind='material',expression=right,evidence=text),dict(id='fc',kind='property',expression='financing options',evidence=text)],alternatives=[],constraints=[],preferences=[],requires_clarification=False,clarification_question=None,confidence=.4))


@pytest.mark.parametrize('left,right',[('photos','brochure'),('pictures','PDF'),('brochure','images'),('blueprints','brochure')])
@pytest.mark.parametrize('verb',['Could you send','Please show me','Can you share'])
def test_mixed_format_variants_preserve_or_and_independent_financing(left,right,verb):
    from app.modules.sales_agent.current_request_repairs import normalize
    text=f'{verb} {left} or a {right} and explain the financing options?'
    u=malformed_mixed(text,left,right);fixed,notes=normalize(u,text,{'property_types':[]})
    assert fixed.confidence==u.confidence and fixed.all_of==['c']
    assert len(fixed.alternatives)==1 and fixed.alternatives[0].request_ids==['a','b']
    assert all(r.reference_id is None for r in fixed.requests) and notes


@pytest.mark.parametrize('prefix',['Do not ','If I asked you to ','My friend said: ','They want you to '])
def test_negative_reported_or_hypothetical_materials_do_not_gain_consent(prefix):
    from app.modules.sales_agent.current_request_repairs import normalize
    text=prefix+'send photos or a brochure and explain the financing options'
    u=malformed_mixed(text);fixed,notes=normalize(u,text,{'property_types':[]})
    assert fixed==u and notes==[]


def test_and_formats_stay_independent_and_named_unknown_targets_survive():
    from app.modules.sales_agent.current_request_repairs import normalize
    text='Please send photos and a brochure and explain financing options'
    u=malformed_mixed(text);fixed,_=normalize(u,text,{'property_types':[]})
    assert fixed.all_of==['a','b','c'] and not fixed.alternatives
    raw=u.model_dump();raw['references'][0]['expression']='Penthouse photos'
    raw['references'][0]['evidence']=text='Please send Penthouse photos and a brochure and explain financing options'
    for r in raw['requests']:r['evidence']=text
    for r in raw['references']:r['evidence']=text
    fixed,_=normalize(Understanding.model_validate(raw),text,{'property_types':[]})
    assert fixed.requests[0].reference_id=='fa'


@pytest.mark.parametrize('part,expected',[('morning',('06:00','12:00')),('afternoon',('12:00','18:00')),('evening',('18:00','24:00'))])
@pytest.mark.parametrize('zone',["use the property's timezone.","Please use the project timezone",'the property’s local time'])
def test_natural_dayparts_and_project_timezone_variants(part,expected,zone):
    from app.modules.sales_agent.first_booking import normalize_timing
    text=f'I would like a visit any {part} in the next seven days; {zone}'
    u=understanding(text,'appointment');u=u.model_copy(update={'visit':{'action':'request','evidence':text,'timing':dict(date_from_evidence='next seven days',time_from_evidence=part,time_relation='any',timezone_evidence=zone)}})
    u=Understanding.model_validate(u.model_dump())
    prefs=normalize_timing(u,text,SimpleNamespace(timezone='America/New_York'),datetime(2026,11,15,12),{})
    assert (prefs['time_from'],prefs['time_until'])==expected and prefs['timezone']=='America/New_York'


def test_tool_requested_temporal_clarification_is_allowed_and_not_a_success(lab):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    db,scope,conv,msg,out=prepared(lab,'I would like a visit at an unclear time',('appointment',))
    data=out.state.last_understanding.model_dump();data['visit']=dict(action='request',evidence=msg.content,timing=None)
    out.state.last_understanding=Understanding.model_validate(data)
    async def infer(messages,schema):
        payload=json.loads(messages[1]['content'])
        return json.dumps({'action':'clarify' if payload['observations'] else 'read','tool_ids':[] if payload['observations'] else ['visit_availability']})
    with sandbox(db,conv,datetime.utcnow()),patch('app.modules.sales_agent.first_booking.normalize_timing',side_effect=ValueError('ambiguous time')):
        result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer))
    assert audit['status']=='CLARIFICATION_REQUIRED' and result.stop_reason=='clarification_required'
    assert all(d['status']=='accepted' for d in audit['decisions']) and audit['decisions'][-1]['action']=='clarify'
    assert audit['external_writes']==0


@pytest.mark.parametrize('status',['pending','blocked','awaiting_user'])
def test_unresolved_task_does_not_become_a_false_loop_pass(lab,status):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    db,scope,conv,msg,out=prepared(lab,'Show photos of an unknown property')
    task=out.state.tasks[0];task.binding_status='unresolved';task.status=status
    async def forbidden(*args):raise AssertionError('No scoped tool exists.')
    with sandbox(db,conv,datetime.utcnow()):result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=forbidden))
    assert audit['status']=='CLARIFICATION_REQUIRED' and task.id in audit['unread_required_tasks']
    assert not audit['decisions'] and not audit['tools']


@pytest.mark.parametrize('zone',['America/Lima','America/Chicago'])
def test_explicit_foreign_timezone_and_clock_are_not_replaced(zone):
    from app.modules.sales_agent.first_booking import normalize_timing
    text=f'I would like a visit tomorrow after 10 AM in {zone}'
    data=understanding(text,'appointment').model_dump();data['visit']=dict(action='request',evidence=text,timing=dict(date_from_evidence='tomorrow',time_from_evidence='10 AM',time_relation='after',timezone_evidence=zone))
    prefs=normalize_timing(Understanding.model_validate(data),text,SimpleNamespace(timezone='America/New_York'),datetime(2026,11,15,12),{})
    assert prefs['time_from']=='10:00' and prefs['time_relation']=='after' and prefs['timezone']==zone


@pytest.mark.parametrize('phrase',['not the property timezone','use Mars/Olympus','the property timezone or America/Lima'])
def test_ambiguous_or_unknown_timezone_still_requires_clarification(phrase):
    from app.modules.sales_agent.first_booking import normalize_timing
    text=f'I would like a visit tomorrow; {phrase}'
    data=understanding(text,'appointment').model_dump();data['visit']=dict(action='request',evidence=text,timing=dict(date_from_evidence='tomorrow',time_relation='any',timezone_evidence=phrase))
    with pytest.raises(ValueError,match='timezone'):
        normalize_timing(Understanding.model_validate(data),text,SimpleNamespace(timezone='America/New_York'),datetime(2026,11,15,12),{})


def test_new_daypart_replaces_old_clock_without_losing_current_limits():
    from app.modules.sales_agent.first_booking import normalize_timing
    text='I would like a visit tomorrow morning after 10 AM'
    data=understanding(text,'appointment').model_dump();data['visit']=dict(action='request',evidence=text,timing=dict(date_from_evidence='tomorrow',time_from_evidence='10 AM',time_relation='morning'))
    previous=dict(time_from='15:00',time_until='18:00',time_relation='range')
    prefs=normalize_timing(Understanding.model_validate(data),text,SimpleNamespace(timezone='UTC'),datetime(2026,11,15,12),previous)
    assert (prefs['time_from'],prefs['time_until'])==('10:00','12:00')


def test_named_material_identity_is_not_rewritten_as_a_generic_format():
    from app.modules.sales_agent.current_request_repairs import normalize
    text='Could you send photos or a brochure and explain financing options?'
    u=malformed_mixed(text)
    fixed,_=normalize(u,text,{'property_types':[],'available_assets':[{'name':'photos'}]})
    assert fixed.requests[0].reference_id=='fa' and fixed.requests[0].subject is None
    assert not fixed.alternatives
