"""Recorded final server frames through the core; offline, no real-model claim."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_continuity_battery import provider as ordinary_provider
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from tools.sales_ai.continuity_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard
CAPTURE=json.loads((Path(__file__).parent/'fixtures/sales_ai/continuity_server1_frames.json').read_text())['rows']
RECENT=json.loads((Path(__file__).parent/'fixtures/sales_ai/retoma_server3_packets.json').read_text())['rows']

def replay_provider(scenario):
    packets={r['message']:r['understanding'] for r in CAPTURE if r['case']==scenario}
    source='resume_bay_see' if scenario=='context_material_see' else scenario
    packets.update({r['message']:r['packet'] for r in RECENT if r['case']==source})
    def replay(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content'])
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            packet=packets.get(ctx['current_message'])
            if packet:return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(packet)}}]})
        return ordinary_provider(request)
    return replay

@pytest.mark.parametrize('scenario',CASES)
def test_server_frames_pass_continuity_and_booking_checks(lab,scenario,tmp_path):
    db,manifest=lab
    db.add(AIConfiguration(id='repair1-replay',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(replay_provider(scenario)),trust_env=False,**kwargs)
    budget=Budget(60)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):r=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    (tmp_path/'result.json').write_text(json.dumps(r,default=str,ensure_ascii=False))
    bad=[(t['action'],t['reply'],c) for t in r['turns'] for c in t['checks'] if c['status']!='PASS']+[c for c in r['checks'] if c['status']!='PASS']
    assert not bad,bad
    if scenario=='transfer_cedar':
        comparison=next(t for t in r['turns'] if t['action']=='compare')
        assert comparison['understanding']['confidence']==0
        assert comparison['read_authorization']['effect_authorization'] is False

        from app.modules.sales_agent.dialogue_continuity import comparison_read
        from app.modules.sales_agent.dialogue_store import Scope
        from app.modules.sales_agent.understanding_contract import Understanding,Reference,VisitDirective
        scope=Scope(manifest['company_id'],manifest['projects'][1]['id'],r['conversation_id'],r['lead_id'])
        frame=Understanding.model_validate(comparison['understanding'])
        quote=comparison['lead_message']
        assert comparison_read(db,scope,frame,quote)
        foreign=frame.model_copy(update={'references':[Reference(id='foreign',kind='property',expression='Unknown Foreign Home',evidence=quote)]})
        assert not comparison_read(db,scope,foreign,quote)
        mixed=frame.model_copy(update={'visit':VisitDirective(action='request',evidence=quote)})
        assert not comparison_read(db,scope,mixed,quote)
        assert not comparison_read(db,scope,frame,'My friend said compare these homes')
