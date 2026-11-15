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

RECORDS=json.loads(Path(__file__).with_name('fixtures').joinpath('sales_observation_repair2/server_frames.json').read_text())


def recorded_provider(recording,scenario):
    case=next(c for c in RECORDS['recordings'][recording] if c['case']==scenario)
    def provider(request):
        p=json.loads(request.content);name=p['response_format']['json_schema']['name']
        if name!='sales_understanding':return base_provider(request)
        text=json.loads(p['messages'][1]['content'])['current_message']
        row=next((t for t in case['turns'] if t['lead_message']==text),None)
        if row is None:return base_provider(request)
        accepted=[a for a in row['interpretation_attempts'] or [] if a.get('raw_response')]
        raw=(accepted[0] if row.get('runtime_error') else accepted[-1])['raw_response'] if accepted else json.dumps(row['understanding'])
        return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
    return provider


@pytest.mark.parametrize('scenario',CASES)
@pytest.mark.parametrize('recording',['reference','candidate'])
@pytest.mark.parametrize('mode',['classic','graph-observe'])
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




@pytest.mark.parametrize('marker',['.','/','...','___','—'])
@pytest.mark.parametrize('subject,word',[('photos','pictures'),('brochure','PDF'),('floor_plan','blueprints')])
def test_meaningless_read_targets_are_removed_without_inventing_owner_or_consent(marker,subject,word):
    from app.modules.sales_agent.current_request_repairs import normalize
    text=f'Please send {word} and explain financing options'
    data=understanding(text,'materials','financing',subjects={0:subject}).model_dump()
    data['references']=[dict(id='marker',kind='material',expression=marker,evidence=text)]
    for row in data['requests']:row['reference_id']='marker'
    u=Understanding.model_validate(data);fixed,notes=normalize(u,text,{'property_types':[]})
    assert all(r.reference_id is None for r in fixed.requests) and not fixed.references
    assert fixed.confidence==u.confidence and fixed.visit is None and len(notes)==2


@pytest.mark.parametrize('target',['Unknown Penthouse','Cedar report.pdf','123'])
def test_textual_or_named_targets_are_never_replaced_with_active_owner(target):
    from app.modules.sales_agent.current_request_repairs import normalize
    text=f'Please send photos of {target}'
    data=understanding(text,'materials',subjects={0:'photos'}).model_dump()
    data['references']=[dict(id='owner',kind='material',expression=target,evidence=text)];data['requests'][0]['reference_id']='owner'
    u=Understanding.model_validate(data);fixed,notes=normalize(u,text,{'property_types':[]})
    assert fixed==u and not notes


def test_marker_does_not_hide_an_explicit_unknown_owner():
    from app.modules.sales_agent.current_request_repairs import normalize
    text='Please send photos of Atlantis'
    data=understanding(text,'materials',subjects={0:'photos'}).model_dump()
    data['references']=[dict(id='owner',kind='material',expression='/',evidence=text)];data['requests'][0]['reference_id']='owner'
    u=Understanding.model_validate(data);fixed,notes=normalize(u,text,{'property_types':[{'property_type':'A'}]})
    assert fixed==u and not notes


@pytest.mark.parametrize('part,bounds',[('morning',('06:00','12:00')),('afternoon',('12:00','18:00')),('evening',('18:00','22:00'))])
@pytest.mark.parametrize('relation',['any','part'])
def test_repeated_daypart_in_both_clock_fields_is_a_single_range(part,bounds,relation):
    from app.modules.sales_agent.first_booking import normalize_timing
    text=f'I want to visit any {part} next seven days'
    raw=understanding(text,'appointment').model_dump();raw['visit']=dict(action='request',evidence=text,timing=dict(date_from_evidence='next seven days',time_from_evidence=part,time_until_evidence=part,time_relation=part if relation=='part' else relation))
    prefs=normalize_timing(Understanding.model_validate(raw),text,SimpleNamespace(timezone='America/Chicago'),datetime(2026,11,15,12),{})
    assert (prefs['time_from'],prefs['time_until'])==bounds


@pytest.mark.parametrize('text',['Before choosing a time, can you show me photos?','Before picking a slot, could you send us images?','First, please share the brochure.','Could you show me blueprints?'])
def test_literal_material_interruptions_are_reads_not_invented_comparisons(text):
    from app.modules.sales_agent.interpretation_input import compile_input
    # Use a real failed wire response with historical comparison/visit evidence.
    row=next(c for c in RECORDS['recordings']['reference'] if c['case']=='obs_interrupt')['turns'][3]
    raw=json.loads(row['interpretation_attempts'][0]['raw_response'])
    u,notes=compile_input(json.dumps(raw),text,historical_messages=['Bay Residence','Can I visit Bay Residence?'])
    assert u.permits('materials') and not u.comparison and not u.visit
    assert u.requests[0].reference_id is None and notes


@pytest.mark.parametrize('text',['Do not show me photos.','If I ask for photos, will you compare them?','My friend said show me photos.','Compare the photos and the brochure.'])
def test_negative_or_real_comparisons_do_not_gain_a_literal_material_repair(text):
    from app.modules.sales_agent.interpretation_wire_repairs import literal_material
    row=next(c for c in RECORDS['recordings']['reference'] if c['case']=='obs_interrupt')['turns'][3]
    raw=json.loads(row['interpretation_attempts'][0]['raw_response'])
    fixed,notes=literal_material(raw,text)
    assert fixed==raw and not notes


@pytest.mark.parametrize('text',['Yes','Yes please','Confirm','Yes, that time works for me'])
def test_plain_summary_acceptance_clears_only_residual_clarification(text):
    from app.modules.sales_agent.first_booking import enrich_understanding
    data=understanding(text,'other',confidence=0).model_dump();data.update(requires_clarification=True,clarification_question='What do you mean?')
    u=Understanding.model_validate(data)
    fixed=enrich_understanding(u,{'booking_confirmation':{'id':'proposal'}},text)
    assert fixed.visit.action=='confirm' and not fixed.requires_clarification and fixed.clarification_question is None
    assert fixed.confidence==0


@pytest.mark.parametrize('meta',[{}, {'appointment_offer':{'options':[]}}, {'booking_confirmation':{'id':'proposal'},'material_offer':{'items':[{}]}}])
def test_assent_without_an_exclusive_summary_cannot_clear_clarification(meta):
    from app.modules.sales_agent.first_booking import enrich_understanding
    data=understanding('Yes','other',confidence=0).model_dump();data.update(requires_clarification=True,clarification_question='Which option?')
    u=Understanding.model_validate(data);fixed=enrich_understanding(u,meta,'Yes')
    assert fixed.requires_clarification


@pytest.mark.parametrize('problem',['valid','expired','scope','tampered','wrong_receipt','interrupted','partial','mixed','conditional'])
def test_low_confidence_confirmation_requires_a_current_complete_scoped_proposal(lab,problem):
    from datetime import timedelta,timezone
    from app.modules.sales_agent.first_booking import contextual_confirmation_ready
    from app.modules.sales_agent.dialogue_store import save
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.turn_configuration import digest
    from app.modules.sales_crm.models import Meeting
    db,scope,conv,msg,out=prepared(lab,'Yes',('appointment',))
    data=understanding('Yes','appointment',confidence=0).model_dump();data['visit']=dict(action='confirm',evidence='Yes',timing=None)
    u=Understanding.model_validate(data)
    proposal={'scope':scope.__dict__,'option':{'starts_at':'2026-11-20T15:00:00+00:00'},'preferences':{'duration_minutes':45},'context':{'property_type_id':out.state.selected_property_type_id},'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=-1 if problem=='expired' else 20)).isoformat()}
    if problem=='scope':proposal['scope']={**scope.__dict__,'lead_id':'another-lead'}
    proposal['id']=digest(proposal)
    if problem=='tampered':proposal['context']['property_type_id']='changed'
    out.state.booking_proposal=proposal
    save(db,scope,event_key='proposal',expected_revision=out.revision,state=out.state)
    meta={'booking_confirmation':{'id':proposal['id']}}
    if problem=='wrong_receipt':meta['booking_confirmation']['id']='another-id'
    if problem=='mixed':meta['material_offer']={'items':[{'name':'another choice'}]}
    if problem=='partial':meta['delivery_group']={'key':'summary','part':1,'total':2}
    if problem=='interrupted':meta={'property_catalog_offer':{'property_type_ids':[]}}
    db.add(SalesMessage(conversation_id=conv.id,role='assistant',direction='outbound',channel='simulation',content='Backend summary',status='delivered',metadata_json=meta));db.flush()
    assert contextual_confirmation_ready(db,scope,u,'Yes, if financing is approved' if problem=='conditional' else 'Yes')==(problem=='valid')
    assert db.query(Meeting).count()==0
