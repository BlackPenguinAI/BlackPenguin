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

RECORD=json.loads((Path(__file__).parent/'fixtures/sales_graph_repair2/server_frames.json').read_text())


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
    if scenario=='obs_switch':
        t=next(t for t in result['turns'] if t['action']=='material')
        assert 'http' in t['reply'] and t['understanding']['confidence']==0
        assert t['read_authorization']['effect_authorization'] is False
        assert len(t['understanding']['references'])==1


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
