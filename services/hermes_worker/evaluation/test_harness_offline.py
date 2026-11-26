"""Offline validation of the E2E fixture; deliberately NOT real SDK evidence."""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog, first_input, next_input, state, tools_for, verify_material_and_replay

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')


def test_harness_with_tool_driven_sdk_double(real_lane, monkeypatch, tmp_path):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    lane = real_lane
    seed_catalog(lane, monkeypatch, tmp_path)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')

    def fake(runtime, request):
        if request.message.startswith('Tell me'):
            tool = 'get_unit_details'
            args = {'unit_id':'van'}
            reply = 'Van Buren has 3 bedrooms.'
        elif request.message.startswith('Can you send'):
            tool = 'get_unit_media'
            args = {'unit_id':'van','media_type':'brochure'}
            reply = 'I found the brochure for Van Buren.'
        elif request.message.startswith('Show me'):
            tool = 'search_properties'
            args = {'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
            reply = '1. Van Buren — 3 bedrooms\n2. Oakwood — 3 bedrooms\nWhich property would you like to explore?'
        elif request.message.startswith('The second'):
            tool = 'get_unit_details'
            args = {'unit_id':'oak'}
            reply = 'Oakwood has 2 bathrooms.'
        else:
            raise AssertionError('Unexpected model invocation')
        outcome = runtime._port.invoke(tool, args, request.scope)
        assert outcome.get('ok'), outcome
        return TurnResult(reply, [], [{'tool':tool,'status':'executed','error_code':None}])

    monkeypatch.setattr(HermesSalesRuntime, 'process_turn', fake)
    mid = first_input(lane, 'Tell me the number of bedrooms in Van Buren.')
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    assert 'get_unit_details' in tools_for(lane, mid)
    mid, jid = next_input(lane, 'Can you send me the PDF?')
    verify_material_and_replay(lane, mid, jid)
    mid, _ = next_input(lane, 'Show me the available 3 bedroom houses under $350,000 as a numbered list.')
    assert state(lane)['last_presented_choice_set']['options'][1]['unit_id'] == 'oak'
    next_input(lane, 'The second option. How many bathrooms does it have?')
    assert state(lane)['conversation_focus']['property_type_id'] == 'oak'
    count = len(lane.sdk_calls)
    next_input(lane,'STOP')
    assert len(lane.sdk_calls) == count and lane.db.get(lane.Lead,'lead').is_opt_out
