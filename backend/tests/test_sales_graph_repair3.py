"""Recorded low-confidence owner/format repair, scoped reads and safe alternatives."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
import pytest,httpx
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from test_sales_observation_loop import provider as base_provider
from app.modules.sales_agent.understanding_contract import Understanding
from tools.sales_ai.observation_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

RECORD=json.loads((Path(__file__).parent/'fixtures/sales_graph_repair3/server_frames.json').read_text())


def recorded_provider(scenario):
    case=next(c for c in RECORD['cases'] if c['case']==scenario)
    def provider(request):
        payload=json.loads(request.content)
        if payload['response_format']['json_schema']['name']!='sales_understanding':return base_provider(request)
        text=json.loads(payload['messages'][1]['content'])['current_message']
        row=next((t for t in case['turns'] if t['lead_message']==text),None)
        if not row or not row['interpretation_attempts']:return base_provider(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':row['interpretation_attempts'][-1]['raw_response']}}]})
    return provider


@pytest.mark.parametrize('scenario',CASES)
def test_latest_server_frames_complete_all_six_journeys(lab,scenario,tmp_path):
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    db,manifest=lab
    db.add(AIConfiguration(id='graph-repair2',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(recorded_provider(scenario)),trust_env=False,**kwargs)
    budget=Budget(150)
    with guard(budget),patch.object(httpx,'AsyncClient',Client),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kwargs:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    (tmp_path/'result.json').write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2))
    assert not [c for t in result['turns'] for c in t['checks'] if c['status']!='PASS']
    assert not [c for c in result['checks'] if c['status']!='PASS']


@pytest.mark.parametrize('name',['Juniper Home','Harbor Flat','Maple Residence'])
@pytest.mark.parametrize('phrase,subject',[
    ('Please send the brochure for {name}.','brochure'),('Could you share the PDF for {name}?','brochure'),
    ('Show me photos of {name}.','photos'),('Please send the blueprints for {name}.','floor_plan'),
])
def test_literal_owner_variants_keep_confidence_and_one_target(name,phrase,subject):
    from app.modules.sales_agent.interpretation_consistency import normalize
    text=phrase.format(name=name);raw=understanding(text,'materials',subjects={0:subject},references=[dict(id='old',kind='material',expression=name,evidence=text)],confidence=0).model_dump()
    raw['requests'][0]['reference_id']='old'
    fixed,notes=normalize(Understanding.model_validate(raw),text,{'property_types':[{'id':'approved','property_type':name}]})
    assert fixed.confidence==0 and not fixed.requires_clarification and notes
    assert len(fixed.references)==1 and fixed.references[0].kind=='property'
    assert fixed.requests[0].subject==subject and fixed.visit is None


@pytest.mark.parametrize('text',[
    'Do not send the brochure for Juniper Home.','If I wanted the PDF for Juniper Home?',
    'My friend said: Send the PDF for Juniper Home.','Send the brochure for Juniper Home or Harbor Flat.',
    'Send the brochure for Unknown Tower.','Send report.pdf for Juniper Home.',
    'Please send the brochure for Juniper Home and book a visit.',
])
def test_unknown_or_mixed_requests_do_not_gain_literal_authorization(text):
    from app.modules.sales_agent.literal_material import named_request
    assert named_request(text,{'property_types':[{'id':'a','property_type':'Juniper Home'},{'id':'b','property_type':'Harbor Flat'}]}) is None


@pytest.mark.parametrize('collision',['duplicate_property','unit','file'])
def test_ambiguous_catalog_names_do_not_gain_literal_authorization(collision):
    from app.modules.sales_agent.literal_material import named_request
    context={'property_types':[{'id':'a','property_type':'Juniper Home'}]}
    if collision=='duplicate_property':context['property_types'].append({'id':'b','property_type':'Juniper Home'})
    if collision=='unit':context['inventory']=[{'unit_code':'Juniper Home'}]
    if collision=='file':context['available_assets']=[{'name':'Juniper Home'}]
    assert named_request('Send the brochure for Juniper Home.',context) is None

@pytest.mark.parametrize('attempt',[0,1])
@pytest.mark.parametrize('name',['Juniper Home','Maple Residence','Harbor Flat'])
@pytest.mark.parametrize('phrase',['Actually I prefer {name} instead.','I choose {name}.',"I'd prefer {name}."])
def test_pure_property_switch_removes_invented_visit_and_comparison(name,phrase,attempt):
    from app.modules.sales_agent.interpretation_wire_repairs import literal_property_choice
    from app.modules.sales_agent.interpretation_input import compile_input
    text=phrase.format(name=name)
    source=json.loads(next(c for c in RECORD['cases'] if c['case']=='obs_switch')['turns'][2]['interpretation_attempts'][attempt]['raw_response'])
    source['confidence']=0
    fixed,notes=literal_property_choice(source,text)
    assert notes and fixed['visit'] is None and fixed['confidence']==0
    value,_=compile_input(json.dumps(fixed),text)
    assert value.comparison is None and value.visit is None
    assert value.references[0].expression==name
    assert all(q.topic.value=='property_details' for q in value.requests)

@pytest.mark.parametrize('text',[
 'I do not prefer Juniper Home.','My friend said I prefer Juniper Home.',
 'If I prefer Juniper Home?','I prefer Juniper Home or Harbor Flat.',
 'I prefer Juniper Home and book a visit.','I prefer Juniper Home tomorrow.',
 'I prefer Juniper Home instead of Harbor Flat.',
])
def test_property_switch_does_not_rewrite_ambiguous_or_effectful_messages(text):
    from app.modules.sales_agent.interpretation_wire_repairs import literal_property_choice
    raw={'requests':[],'confidence':0}
    assert literal_property_choice(raw,text)==(raw,[])

@pytest.mark.parametrize('phrase',[
 'Could you send photos or a brochure and explain the financing options?',
 'Please show me pictures or the PDF and describe payment options.',
 'Can you share images or a brochure and explain financing options?',
])
def test_mixed_reads_require_active_scoped_owner_and_do_not_raise_confidence(lab,monkeypatch,phrase):
    from app.modules.sales_agent.dialogue_continuity import mixed_material_financing_read
    from app.modules.sales_agent.dialogue_store import Scope
    from app.modules.sales_agent.understanding_contract import Understanding
    from types import SimpleNamespace
    # Isolate capability boundary: resolving the active owner is independently
    # covered by complete recorded journeys above; no write is performed here.
    monkeypatch.setattr('app.modules.sales_agent.dialogue_store.load',lambda *a:(0,SimpleNamespace(selected_property_type_id='owned',selected_unit_id=None)))
    class Resolver:
        def __init__(self,*a):pass
        def bound(self,kind,key):return key=='owned'
    monkeypatch.setattr('app.modules.sales_agent.reference_resolution.Resolver',Resolver)
    raw=understanding(phrase,'materials',confidence=0).model_dump()
    raw.update(requests=[dict(id='p',topic='materials',subject='photos',polarity='request',evidence=phrase),dict(id='b',topic='materials',subject='brochure',polarity='request',evidence=phrase),dict(id='f',topic='financing',polarity='request',evidence=phrase)],all_of=['f'],alternatives=[dict(id='or',request_ids=['p','b'],evidence=phrase)])
    value=Understanding.model_validate(raw)
    assert mixed_material_financing_read(None,None,value,phrase) and value.confidence==0
    for update in ({'visit':{'action':'request','evidence':phrase}}, {'all_of':['p','b','f'],'alternatives':[]}, {'references':[dict(id='x',kind='property',expression='Other',evidence=phrase)]}):
        assert not mixed_material_financing_read(None,None,Understanding.model_validate({**raw,**update}),phrase)
    monkeypatch.setattr('app.modules.sales_agent.dialogue_store.load',lambda *a:(0,SimpleNamespace(selected_property_type_id=None,selected_unit_id=None)))
    assert not mixed_material_financing_read(None,None,value,phrase)
