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

RECORD=json.loads((Path(__file__).parent/'fixtures/sales_context_replay/server_frames.json').read_text())


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
