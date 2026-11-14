"""Replay recorded server interpretations through the real core; offline network."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_compact_battery import provider
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.needs_search import literal_read,normalize
from app.modules.sales_agent.understanding_contract import Understanding
from tools.sales_ai.needs_discovery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

CAPTURE=json.loads((Path(__file__).parent/'fixtures/sales_ai/needs_discovery_1_interpretations.json').read_text())['rows']

@pytest.mark.parametrize('scenario',CASES)
def test_recorded_failed_interpretations_now_meet_needs_checks(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='replay-needs',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    packets={r['message']:r['understanding'] for r in CAPTURE if r['case']==scenario}
    def replay(request):
        payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content'])
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(packets[context['current_message']])}}]})
        return provider(request)
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(replay),trust_env=False,**kwargs)
    with patch.object(httpx,'AsyncClient',Client),guard(Budget(20)),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,Budget(20),3))
    failures=[(r['lead_message'],r['reply'],c) for r in result['turns'] for c in r['checks'] if c['status']=='FAIL']
    assert not failures,failures
    if scenario=='no_premature_selection':
        assert result['turns'][-1]['understanding']['confidence']==0
        assert result['turns'][-1]['read_authorization']['model_confidence']==0
        assert result['turns'][-1]['read_authorization']['effect_authorization'] is False


@pytest.mark.parametrize('text',['I need a 2 bedroom home. Compare the options.','I need a 2 bedroom home and financing.','I need at least 2 bedrooms.','I need a 2 bedroom home. Book a visit.','My friend said I need a 2 bedroom home.'])
def test_literal_authorization_never_extends_to_mixed_ambiguous_or_effect_requests(text):
    frame,_=normalize(understanding(text,'catalog',confidence=0),text,{'property_types':[]})
    assert not literal_read(frame,text)


def test_explicit_comparison_is_preserved_and_read_confidence_never_raised():
    row=next(r for r in CAPTURE if r['case']=='exact_two');value=Understanding.model_validate(row['understanding'])
    fixed,notes=normalize(value,row['message'],{'property_types':[]})
    assert fixed.comparison is None and not fixed.references and fixed.confidence==value.confidence
    text='I need a 2 bedroom home. Compare the options.'
    data=value.model_dump();data['requests'][0]['evidence']=text;data['comparison']['evidence']=text
    unchanged=Understanding.model_validate(data)
    assert normalize(unchanged,text,{'property_types':[]})==(unchanged,[])
