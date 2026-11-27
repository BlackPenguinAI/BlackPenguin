"""Offline validation of the E2E fixture; deliberately NOT real SDK evidence."""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from focus_grounding import FocusGrounding, assert_fact_reply
from sdk_scenarios import hei06_lane_engine, seed_catalog, first_input, next_input, state, tools_for, observations_for, verify_material_and_replay

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')


def test_harness_with_tool_driven_sdk_double(real_lane, monkeypatch, tmp_path):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    lane = real_lane
    seed_catalog(lane, monkeypatch, tmp_path)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')

    proof = FocusGrounding()

    def fake(runtime, request):
        proof.observe(request)
        if request.message.startswith('Tell me'):
            # Reproduce evaluation #10: answer from actual verified context,
            # without manufacturing a successful tool call.
            prop = request.verified_context['focused_property']
            return TurnResult(f"{prop['display_name']} has {prop['bedrooms']} bedrooms.", [], [])
        elif request.message.startswith('Can you send'):
            tool = 'get_unit_media'
            args = {'unit_id':'van','media_type':'brochure'}
            reply = 'I found the brochure for Van Buren.'
        elif request.message.startswith('Show me'):
            tool = 'search_properties'
            args = {'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
            reply = 'Here are the 3 bedroom houses under $350,000:\n1. Van Buren — $325k\n2. Oakwood — $340k\nWhich property would you like to explore?'
        elif request.message.startswith('The second'):
            tool = 'get_unit_details'
            args = {'unit_id':'oak'}
            reply = 'Oakwood has 2 bathrooms.'
        else:
            raise AssertionError('Unexpected model invocation')
        outcome = runtime._port.invoke(tool, args, request.scope)
        assert outcome.get('ok'), outcome
        observations = [{'tool':tool,'status':'executed','error_code':None}]
        if tool == 'search_properties':
            # Reproduce the real SDK's second numbered-choice repetition from
            # HEI-06 run #8: a successful search followed by a scoped overview.
            overview = runtime._port.invoke('get_project_overview', {}, request.scope)
            assert overview.get('ok'), overview
            observations.append({'tool':'get_project_overview','status':'executed','error_code':None})
        return TurnResult(reply, [], observations)

    monkeypatch.setattr(HermesSalesRuntime, 'process_turn', fake)
    message = 'Tell me the number of bedrooms in Van Buren.'
    proof.expect(scope=lane.scope, message=message, ref='van', name='Van Buren', field='bedrooms', value=3)
    mid = first_input(lane, message)
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    assert proof.finish(observations=observations_for(lane, mid)) == 'verified_context'
    assert 'get_unit_details' not in tools_for(lane, mid)
    assert_fact_reply(lane.calls[-1], name='Van Buren', field='bedrooms', value=3)
    mid, jid = next_input(lane, 'Can you send me the PDF?')
    verify_material_and_replay(lane, mid, jid)
    mid, _ = next_input(lane, 'Show me the available 3 bedroom houses under $350,000 as a numbered list.')
    # The original model reply would be rejected by the unchanged guard. The
    # actual accepted SMS must contain both verified full prices, not the
    # echoed buyer ceiling, and must retain the original numbered choice.
    assert '1. Van Buren: starting price USD 325,000' in lane.calls[-1]
    assert '2. Oakwood: starting price USD 340,000' in lane.calls[-1]
    assert '$350,000' not in lane.calls[-1] and '$325k' not in lane.calls[-1]
    assert {'search_properties','get_project_overview'} <= tools_for(lane, mid)
    assert state(lane)['last_presented_choice_set']['options'][1]['unit_id'] == 'oak'
    message = 'The second option. How many bathrooms does it have?'
    proof.expect(scope=lane.scope, message=message, ref='oak', name='Oakwood', field='bathrooms', value=2, ordinal=True)
    mid, _ = next_input(lane, message)
    assert proof.finish(observations=observations_for(lane, mid)) == 'verified_context_and_tool'
    assert_fact_reply(lane.calls[-1], name='Oakwood', field='bathrooms', value=2)
    assert state(lane)['conversation_focus']['property_type_id'] == 'oak'
    count = len(lane.sdk_calls)
    next_input(lane,'STOP')
    assert len(lane.sdk_calls) == count and lane.db.get(lane.Lead,'lead').is_opt_out
