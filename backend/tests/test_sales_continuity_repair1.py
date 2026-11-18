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
SERVER7=json.loads((Path(__file__).parent/'fixtures/sales_ai/material_server7_packets.json').read_text())['rows']
SERVER6=json.loads((Path(__file__).parent/'fixtures/sales_ai/coherence_server6_packets.json').read_text())['rows']
LATEST=json.loads((Path(__file__).parent/'fixtures/sales_ai/visit_server5_packets.json').read_text())['rows']
CURRENT=json.loads((Path(__file__).parent/'fixtures/sales_ai/contextual_server4_packets.json').read_text())['rows']
RECENT=json.loads((Path(__file__).parent/'fixtures/sales_ai/retoma_server3_packets.json').read_text())['rows']

def replay_provider(scenario):
    packets={r['message']:r['understanding'] for r in CAPTURE if r['case']==scenario}
    source='resume_bay_see' if scenario=='context_material_see' else scenario
    packets.update({r['message']:r['packet'] for r in RECENT if r['case']==source})
    def replay(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content'])
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            from app.modules.sales_agent.interpretation_input import SYSTEM
            assert payload['messages'][0]['content']==SYSTEM
            assert 'visit.action=request requires an appointment request' in SYSTEM
            observed=next((r for r in [*SERVER7,*SERVER6,*LATEST,*CURRENT] if r['case']==scenario and r['message']==ctx['current_message']),None)
            if observed:
                attempt=1 if len(payload['messages'])>2 else 0
                packet=observed['sequence'][min(attempt,len(observed['sequence'])-1)]
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(packet)}}]})
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
    from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
    from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION
    for event in db.query(SalesDialogueEvent).filter(SalesDialogueEvent.conversation_id==r['conversation_id'],SalesDialogueEvent.event_key.like('active-understanding:%')):
        metadata=event.payload_json['metadata']
        snapshot=metadata['prompt_snapshot']
        if metadata.get('inference_mode')=='deterministic':
            # Only the exact scoped receipt types skip a model request.
            # A day choice searches availability; it NEVER authorizes booking.
            from app.modules.sales_agent.booking_fastpath import VERSION as BOOKING_VERSION
            from app.modules.sales_agent.visit_day_funnel import VERSION as DAY_VERSION
            contracts={'deterministic-booking-acceptance':BOOKING_VERSION,
                       'deterministic-visit-day':DAY_VERSION}
            assert metadata['model'] in contracts
            expected=contracts[metadata['model']]
            assert metadata['input_contract']==expected
            assert snapshot=={'version':expected,'model_invoked':False,'system':None}
            assert metadata['interpretation_attempts']==[]
            if expected==DAY_VERSION:assert metadata['effect_authorization'] is False
        else:
            assert snapshot['input_system_version']==SYSTEM_VERSION
    bad=[(t['action'],t['reply'],c) for t in r['turns'] for c in t['checks'] if c['status']!='PASS']+[c for c in r['checks'] if c['status']!='PASS']
    assert not bad,bad
    if scenario=='context_visit_see':
        clarified=next(t for t in r['turns'] if t['action']=='visit_clarified')
        assert clarified['understanding']['confidence']==1
        # P3-B may return a verified day offer before slot options. The
        # scripted buyer must advance day -> slots -> explicit confirmation.
        day_offer=clarified['metadata'].get('visit_day_offer')
        slot_offer=clarified['metadata'].get('appointment_offer')
        assert (day_offer or slot_offer) and not clarified['metadata'].get('meeting_id')
        if day_offer:
            day_turn=next(t for t in r['turns'] if t['action']=='select_day')
            assert day_turn['metadata'].get('appointment_offer')
            assert not day_turn['meeting_ids']
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
