"""Opt-in real pinned Nous SDK + OpenRouter; native BP path, fake providers.

No fake model, no production database or real message delivery. The model is
fixed to the published synthetic baseline (openai/gpt-4o-mini). Failure is
blocking evidence, never a retry-until-pass or a substituted SDK.
"""
import os
import re
import pytest
from diagnostics import PROPERTY, SafeTrace
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog, first_input, next_input, state, tools_for, verify_material_and_replay

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')


@pytest.fixture(autouse=True)
def explicit_model_opt_in():
    assert os.environ.get('HEI06_RUN_MODEL') == '1', 'Explicit opt-in is required'
    assert os.environ.get('ENVIRONMENT') == 'test' and os.environ.get('DATABASE_URL') == 'sqlite://'
    assert os.environ.get('OPENROUTER_API_KEY') and os.environ['OPENROUTER_API_KEY'] != 'test-only'
    # The actual installed SDK must be available. Do not replace AIAgent.
    from run_agent import AIAgent
    assert callable(AIAgent)


@pytest.fixture
def trace(real_lane, monkeypatch, record_property):
    """Observe the actual SDK and worker; no replacement of responses or effects."""
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    t = SafeTrace()
    runtime_original = HermesSalesRuntime.process_turn
    prepare_original = real_lane.sdk_service.prepare_reserved
    worker_original = real_lane.job.run_job

    def observed_runtime(runtime, request):
        t.add('runtime_started')
        try:
            result = runtime_original(runtime, request)
        except Exception as exc:
            t.error('runtime_error', exc)
            raise
        t.add('runtime_returned')
        t.tools(result.tool_observations)
        t.reply(result.reply, 'sdk')
        return result

    def observed_prepare(db, request):
        t.add('prepare_started')
        try:
            result = prepare_original(db, request)
        except Exception as exc:
            # The real HTTP boundary intentionally hides the exception in 409.
            # Classify it here without exporting arbitrary exception contents.
            t.error('prepare_error', exc)
            raise
        t.add('prepare_returned')
        return result

    async def observed_worker(*args, **kwargs):
        t.add('worker_started')
        before = len(real_lane.calls)
        try:
            result = await worker_original(*args, **kwargs)
        except Exception as exc:
            t.error('worker_error', exc)
            raise
        t.add('worker_returned')
        for reply in real_lane.calls[before:]:
            t.reply(reply, 'outbound')
        return result

    monkeypatch.setattr(HermesSalesRuntime, 'process_turn', observed_runtime)
    monkeypatch.setattr(real_lane.sdk_service, 'prepare_reserved', observed_prepare)
    monkeypatch.setattr(real_lane.job, 'run_job', observed_worker)
    try:
        yield t
    finally:
        record_property(PROPERTY, t.serialized())


@pytest.mark.parametrize('repeat', [1,2], ids=['repeat-1','repeat-2'])
def test_named_focus_pdf_followup_and_idempotency(real_lane, monkeypatch, tmp_path, repeat, trace):
    lane = real_lane
    trace.checkpoint('seed_catalog')
    seed_catalog(lane, monkeypatch, tmp_path)
    trace.checkpoint('named_details_turn')
    mid = first_input(lane, 'Tell me the number of bedrooms in Van Buren.')
    trace.checkpoint('named_focus')
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    trace.checkpoint('named_details_tool')
    assert 'get_unit_details' in tools_for(lane, mid)
    trace.checkpoint('named_reply_property')
    assert 'van buren' in lane.calls[-1].casefold()
    trace.checkpoint('named_reply_bedrooms')
    assert re.search(r'\b(?:3|three)\s+bedrooms?\b', lane.calls[-1], re.I)
    trace.checkpoint('implicit_pdf_turn')
    mid, jid = next_input(lane, 'Can you send me the PDF?')
    trace.checkpoint('pdf_focus')
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    verify_material_and_replay(lane, mid, jid, trace=trace)
    calls_before = len(lane.sdk_calls)
    trace.checkpoint('stop_turn')
    next_input(lane, 'STOP')
    trace.checkpoint('stop_no_inference')
    assert len(lane.sdk_calls) == calls_before
    trace.checkpoint('stop_opt_out')
    assert lane.db.get(lane.Lead,'lead').is_opt_out
    trace.checkpoint('complete')


@pytest.mark.parametrize('repeat', [1,2], ids=['repeat-1','repeat-2'])
def test_numbered_menu_and_second_option(real_lane, monkeypatch, tmp_path, repeat, trace):
    lane = real_lane
    trace.checkpoint('seed_catalog')
    seed_catalog(lane, monkeypatch, tmp_path)
    trace.checkpoint('numbered_search_turn')
    mid = first_input(lane, 'Show me the available 3 bedroom houses under $350,000 as a numbered list.')
    trace.checkpoint('numbered_search_tool')
    assert 'search_properties' in tools_for(lane, mid)
    trace.checkpoint('numbered_menu_shape')
    menu = state(lane)['last_presented_choice_set']
    assert menu and menu['type'] == 'property' and len(menu['options']) == 2
    trace.checkpoint('numbered_menu_refs')
    assert {option['unit_id'] for option in menu['options']} == {'van','oak'}
    second = menu['options'][1]['unit_id']
    trace.checkpoint('second_option_turn')
    mid, _ = next_input(lane, 'The second option. How many bathrooms does it have?')
    trace.checkpoint('second_option_focus')
    assert state(lane)['conversation_focus']['property_type_id'] == second
    trace.checkpoint('second_option_details_tool')
    assert 'get_unit_details' in tools_for(lane, mid)
    trace.checkpoint('second_option_reply_property')
    assert ('van buren' if second == 'van' else 'oakwood') in lane.calls[-1].casefold()
    trace.checkpoint('second_option_reply_bathrooms')
    assert re.search(r'\b(?:2|two)\s+bathrooms?\b', lane.calls[-1], re.I)
    trace.checkpoint('second_option_run_count')
    assert lane.db.query(lane.Run).count() == 2
    trace.checkpoint('complete')
