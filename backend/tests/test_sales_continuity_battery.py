"""Real core, synthetic SQLite and simulated provider: not real-model quality."""
import asyncio,json,re
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_compact_battery import provider as base_provider
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from tools.sales_ai.continuity_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard


def provider(request):
    payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
    if payload['response_format']['json_schema']['name']!='sales_understanding':return base_provider(request)
    names=[p['property_type'] for p in ctx['approved_context']['property_types']]
    topic='appointment' if re.search(r'\b(?:visit|viewing)\b',text,re.I) or text=='Yes' else 'catalog'
    if text in {'Visit?','A viewing?','Can I see it?'}:topic='appointment'
    if re.search(r'\b(?:blueprints|pictures|photos)\b',text,re.I):topic='materials'
    data=understanding(text,topic,subjects={0:'floor_plan' if 'blueprints' in text.lower() else 'photos'} if topic=='materials' else None).model_dump(mode='json')
    for name in names:
        if name.casefold() in text.casefold():
            data['references'].append(dict(id='owner',kind='property',expression=name,evidence=name));data['requests'][0]['reference_id']='owner';break
    if topic=='appointment' and text!='Yes':data['visit']=dict(action='request',evidence=text,timing=None)
    if text in {'Visit?','A viewing?','Can I see it?'}:data['requests']=[];data['all_of']=[]
    history=ctx.get('history') or []
    previous=next((m['content'] for m in reversed(history) if m.get('role')=='assistant'),'')
    if text=='Can I see it?' and 'share' in previous.lower() and 'visit' not in previous.lower():
        data=understanding(text,'materials').model_dump(mode='json')
        data['references']=[dict(id='material',kind='material',expression=names[0]+' gallery',evidence=text)]
        data['requests'][0]['reference_id']='material'
    if text=='Hi':
        data=understanding(text,confidence=0).model_dump(mode='json')
        data['courtesy']=dict(kind='greeting',evidence=text)
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]})

def recorded_failure_provider(request):
    response=provider(request)
    payload=json.loads(request.content)
    if payload['response_format']['json_schema']['name']!='sales_understanding':return response
    ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
    data=json.loads(response.json()['choices'][0]['message']['content'])
    if data.get('visit') and data['visit']['action']=='request':
        # Short directives deliberately have no executable request in the base
        # frame. Build the misleading catalog frame explicitly, never index []
        # and mistake a test-double IndexError for a model/provider failure.
        if not data['requests']:
            data['requests']=[dict(id='r0',topic='catalog',subject=None,polarity='request',evidence=text)]
            data['all_of']=['r0']
        data['requests'][0]['topic']='catalog'
        data['comparison']=dict(request_id='r0',reference_ids=[r['id'] for r in data['references']],include_current=True,include_all=False,all_kind='property',criteria=['general'],operation='compare',evidence=text)
        data['visit']['timing']=dict(timezone_evidence=text)
    elif re.search(r'photos|blueprints',text,re.I):
        data['requests'][0].update(topic='materials',subject='floor_plan' if 'blueprints' in text else 'photos',reference_id='bad_anaphor')
        data['references']=[dict(id='bad_anaphor',kind='property',expression='/',evidence=text)]
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]})


@pytest.mark.parametrize('response_provider',[provider,recorded_failure_provider],ids=['ordinary_mock','recorded_failure_shapes'])
@pytest.mark.parametrize('scenario',CASES)
def test_multiturn_variants_keep_property_and_reach_verified_goal(lab,scenario,response_provider):
    db,manifest=lab
    db.add(AIConfiguration(id='continuity-offline',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(response_provider),trust_env=False,**kwargs)
    budget=Budget(60)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):result=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    errors=[(r['action'],r['reply'],c) for r in result['turns'] for c in r['checks'] if c['status']!='PASS']+[c for c in result['checks'] if c['status']!='PASS']
    assert not errors,errors

@pytest.mark.parametrize('text',['Visit?','A viewing?','Can I see it?'])
def test_recorded_failure_double_returns_a_frame_for_empty_request_variants(text):
    from app.modules.sales_agent.understanding_contract import Understanding
    request=httpx.Request('POST','https://offline.invalid',json={
        'response_format':{'json_schema':{'name':'sales_understanding'}},
        'messages':[{}, {'content':json.dumps({'current_message':text,'approved_context':{'property_types':[]}})}]})
    payload=recorded_failure_provider(request).json()
    frame=Understanding.model_validate(json.loads(payload['choices'][0]['message']['content'])).check_evidence(text)
    assert frame.visit.action=='request' and frame.comparison is not None
    assert frame.requests[0].topic.value=='catalog' and frame.all_of==['r0']
