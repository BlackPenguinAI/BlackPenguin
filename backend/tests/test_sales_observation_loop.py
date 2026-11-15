"""Result-driven loop: real core, deterministic providers, no paid-model claim."""
import asyncio,json,re
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_continuity_battery import provider as fallback
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.coordinator_graph import experiment
from tools.sales_ai.observation_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard


def provider(request):
    p=json.loads(request.content);name=p['response_format']['json_schema']['name'];ctx=json.loads(p['messages'][1]['content'])
    if name=='sales_observation_decision':
        choices=ctx['available_tools']
        materials=[k for k,v in choices.items() if v['topic']=='materials' and not v.get('discovery_only')]
        ordinary=[k for k,v in choices.items() if not v.get('discovery_only')]
        required=[k for k in ordinary if choices[k]['topic']!='materials']
        keys=(materials[:1]+required)[:4] or ordinary[:4] or list(choices)[:1]
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'action':'read' if keys else 'respond','tool_ids':keys})}}]})
    if name!='sales_understanding':return fallback(request)
    text=ctx['current_message'];names=[r['property_type'] for r in ctx['approved_context']['property_types']]
    topic='materials' if re.search(r'photos|pictures|images|brochure',text,re.I) else 'appointment' if 'visit' in text.lower() else 'catalog'
    if text in names or text.startswith('Actually I prefer'):topic='property_details'
    subject='brochure' if 'brochure' in text.lower() and 'photos' not in text.lower() else 'photos'
    data=understanding(text,topic,subjects={0:subject} if topic=='materials' else None).model_dump(mode='json')
    for name in names:
        if name in text:
            data['references']=[dict(id='owner',kind='property',expression=name,evidence=name)];data['requests'][0]['reference_id']='owner';break
    if 'photos or a brochure' in text:
        data.update(requests=[dict(id='photos',topic='materials',subject='photos',polarity='request',evidence=text),dict(id='brochure',topic='materials',subject='brochure',polarity='request',evidence=text),dict(id='financing',topic='financing',polarity='request',evidence=text)],all_of=['financing'],alternatives=[dict(id='either',request_ids=['photos','brochure'],evidence=text)])
    if topic=='appointment':
        data['visit']=dict(action='request',evidence=text)
        if 'next seven days' in text:data['visit']['timing']=dict(date_from_evidence='next seven days',time_relation='morning',timezone_evidence="the property's timezone")
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(data)}}]})


@pytest.mark.parametrize('scenario',CASES)
@pytest.mark.parametrize('mode',['classic','graph-observe'])
def test_six_journeys_use_same_core_and_safe_booking_contract(lab,scenario,mode,tmp_path):
    db,manifest=lab
    db.add(AIConfiguration(id='obs-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kw):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kw)
    budget=Budget(100)
    with experiment(mode),guard(budget),patch.object(httpx,'AsyncClient',Client),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    (tmp_path/'result.json').write_text(json.dumps(result,default=str,ensure_ascii=False))
    bad=[(t['action'],t['reply'],c) for t in result['turns'] for c in t['checks'] if c['status']!='PASS']+[c for c in result['checks'] if c['status']!='PASS']
    assert not bad,bad
    if mode=='graph-observe':
        decisions=[d for t in result['turns'] for d in t['observation_loop']['decisions']]
        assert any(d.get('observed_operations') for d in decisions)
        assert all(t['observation_loop']['rounds']<=2 for t in result['turns'])
        assert all(t['coordinator_graph']['mode']==mode for t in result['turns'])
        assert all(t['metadata']['planning']['additional_model_calls']==len(t['observation_loop']['decisions']) for t in result['turns'])


def test_catalog_comparison_ignores_only_ephemeral_asset_identity(tmp_path):
    import zipfile
    from tools.sales_ai.compare_graph_runs import compare
    base=dict(commit='same',version='same',sales_model='same',configuration_sha256='same',configuration_version=8,cases=[dict(case='x',turns=[{'checks':[]}],checks=[])])
    def write(name,price=10,sha='same'):
        catalog={'projects':[{'properties':[{'price':price,'resources':[{'asset_id':name,'sha256':sha,'coverage':'photos'}]}]}]}
        with zipfile.ZipFile(tmp_path/(name+'.zip'),'w') as z:
            z.writestr('report.json',json.dumps({**base,'coordinator_mode':'classic' if name=='a' else 'graph-observe'}));z.writestr('catalog.json',json.dumps(catalog))
    write('a');write('b');assert compare(tmp_path/'a.zip',tmp_path/'b.zip')['status']=='COMPARABLE'
    write('b',price=11);assert compare(tmp_path/'a.zip',tmp_path/'b.zip')['status']=='NOT_COMPARABLE'
    write('b',sha='changed');assert compare(tmp_path/'a.zip',tmp_path/'b.zip')['status']=='NOT_COMPARABLE'


def test_missing_mode_trace_fails_without_erasing_dialogue():
    from tools.sales_ai.booking_pilot_worker import annotate_mode
    case={'case':'recorded','turns':[{'reply':'Original reply','coordinator_graph':None,'checks':[]}],'checks':[]}
    assert annotate_mode(case,'classic') is case
    assert case['turns'][0]['reply']=='Original reply' and case['checks'][-1]['status']=='FAIL'


def prepared(lab,text,topics=('materials',)):
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation,SalesMessage
    from app.modules.sales_agent.dialogue_store import Scope,save
    from app.modules.sales_agent.understanding_contract import DialogueState
    from app.modules.sales_agent.execution import sandbox
    from app.modules.sales_agent.dialogue_orchestrator import run_turn
    from datetime import datetime
    db,manifest=lab;project=manifest['projects'][1];prop=project['properties'][1]
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Synthetic Loop',phone='+15550105555',is_demo=True,consent_status='granted_simulation',agent_status='simulation');db.add(lead);db.flush()
    conv=SalesConversation(company_id=lead.company_id,project_id=project['id'],lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False);db.add(conv);db.flush()
    msg=SalesMessage(conversation_id=conv.id,role='user',direction='inbound',channel='simulation',content=text,status='received');db.add(msg);db.flush()
    scope=Scope(lead.company_id,project['id'],conv.id,lead.id)
    state=DialogueState(selected_property_type_id=prop['id']);rev,_=save(db,scope,event_key='known',expected_revision=0,state=state);db.commit()
    u=understanding(text,*topics,subjects={0:'photos'} if topics[0]=='materials' else None)
    with sandbox(db,conv,datetime.utcnow()):out=run_turn(db,scope,message_id=msg.id,understanding=u,expected_revision=rev,event_key='prep',prepare_only=True)
    return db,scope,conv,msg,out


@pytest.mark.parametrize('action',['unknown','repeat','premature','premature_OR','extra_field'])
def test_invalid_model_decisions_do_not_repeat_reads_or_authorize_writes(lab,action):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    from app.modules.sales_crm.models import Meeting
    from app.modules.projects.models import SalesAssetShare
    from app.modules.sales_agent.models import OutboundMessage
    from datetime import datetime
    db,scope,conv,msg,out=prepared(lab,'Please show photos')
    if action=='premature_OR':
        for task in out.state.tasks:task.alternative_group='either'
    seen=[];first=None
    async def infer(messages,schema):
        nonlocal first
        ctx=json.loads(messages[1]['content']);seen.append(ctx)
        if action in {'premature','premature_OR'}:return json.dumps({'action':'respond','tool_ids':[]})
        if action=='extra_field':return json.dumps({'action':'read','tool_ids':[],'book':True})
        if action=='unknown':return json.dumps({'action':'read','tool_ids':['book_a_visit']})
        if first is None:first=next(iter(ctx['available_tools']))
        return json.dumps({'action':'read','tool_ids':[first]})
    with sandbox(db,conv,datetime.utcnow()):result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer))
    assert audit['status']=='FAIL' and audit['external_writes']==0
    assert len(audit['tools'])==int(action=='repeat')
    assert db.query(Meeting).count()==db.query(SalesAssetShare).count()==db.query(OutboundMessage).count()==0
    assert audit['decisions'][-1]['status']=='decision_rejected'


def test_two_round_limit_preserves_unanswered_requests_and_exposes_observations(lab):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    from datetime import datetime
    db,scope,conv,msg,out=prepared(lab,'Show photos and financing and prices',('materials','financing','pricing'))
    seen=[]
    async def infer(messages,schema):
        ctx=json.loads(messages[1]['content']);seen.append(ctx)
        allowed=ctx['available_tools']
        keys=[k for k in allowed if k.startswith('read_')]
        return json.dumps({'action':'read' if keys else 'respond','tool_ids':keys[:1]})
    with sandbox(db,conv,datetime.utcnow()):result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer))
    assert audit['rounds']==2 and len(seen)==3
    assert [len(c['observations']) for c in seen]==[0,1,2]
    assert seen[-1]['available_tools']=={} and audit['unread_required_tasks']
    assert audit['status']=='PARTIAL'


def test_a_real_restriction_blocks_discovery_without_model_or_write(lab):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    from datetime import datetime
    db,scope,conv,msg,out=prepared(lab,'Do not send photos')
    async def forbidden(*args):raise AssertionError('Model should not run for a prohibited read.')
    with sandbox(db,conv,datetime.utcnow()):result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=forbidden))
    assert audit['tools']==[] and audit['decisions']==[] and result.state.constraints


def test_observation_candidate_is_not_available_for_live_traffic():
    from app.modules.sales_agent.coordinator_graph import execute
    async def forbidden():raise AssertionError('No live stage should execute.')
    with experiment('graph-observe'),pytest.raises(PermissionError):
        asyncio.run(execute(None,interpret=forbidden,assess=lambda:False,reconsider=forbidden,plan=forbidden,observe=forbidden,fulfill=forbidden))


def test_existing_comparison_gateway_remains_available_in_observation_loop(lab):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import sandbox
    from app.modules.sales_agent.understanding_contract import Comparison
    from datetime import datetime
    db,scope,conv,msg,out=prepared(lab,'Compare all property options',('catalog',))
    task=out.state.tasks[0]
    out.state.last_understanding.comparison=Comparison(request_id=task.request_ids[0],include_all=True,criteria=['bedrooms'],evidence=msg.content)
    async def infer(messages,schema):
        ctx=json.loads(messages[1]['content']);keys=list(ctx['available_tools'])
        return json.dumps({'action':'read' if keys else 'respond','tool_ids':keys})
    with sandbox(db,conv,datetime.utcnow()):result,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer))
    assert audit['status']=='PASS'
    data=result.results[0].data
    assert data['comparison_text'] and set(data['comparison_property_ids'])=={p['id'] for p in lab[1]['projects'][1]['properties']}
    assert result.state.pending_comparison is None
