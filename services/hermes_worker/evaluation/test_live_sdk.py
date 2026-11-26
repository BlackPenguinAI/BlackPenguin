"""Opt-in real pinned Nous SDK + OpenRouter; native BP path, fake providers.

No fake model, no production database or real message delivery. The model is
fixed to the published synthetic baseline (openai/gpt-4o-mini). Failure is
blocking evidence, never a retry-until-pass or a substituted SDK.
"""
import os
import re
import pytest
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


@pytest.mark.parametrize('repeat', [1,2], ids=['repeat-1','repeat-2'])
def test_named_focus_pdf_followup_and_idempotency(real_lane, monkeypatch, tmp_path, repeat):
    lane = real_lane
    seed_catalog(lane, monkeypatch, tmp_path)
    mid = first_input(lane, 'Tell me the number of bedrooms in Van Buren.')
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    assert 'get_unit_details' in tools_for(lane, mid)
    assert 'van buren' in lane.calls[-1].casefold()
    assert re.search(r'\b(?:3|three)\s+bedrooms?\b', lane.calls[-1], re.I)
    mid, jid = next_input(lane, 'Can you send me the PDF?')
    assert state(lane)['conversation_focus']['property_type_id'] == 'van'
    verify_material_and_replay(lane, mid, jid)
    # The control turn must be deterministic, not a further model call.
    calls_before = len(lane.sdk_calls)
    next_input(lane, 'STOP')
    assert len(lane.sdk_calls) == calls_before
    assert lane.db.get(lane.Lead,'lead').is_opt_out


@pytest.mark.parametrize('repeat', [1,2], ids=['repeat-1','repeat-2'])
def test_numbered_menu_and_second_option(real_lane, monkeypatch, tmp_path, repeat):
    lane = real_lane
    seed_catalog(lane, monkeypatch, tmp_path)
    mid = first_input(lane, 'Show me the available 3 bedroom houses under $350,000 as a numbered list.')
    assert 'search_properties' in tools_for(lane, mid)
    menu = state(lane)['last_presented_choice_set']
    assert menu and menu['type'] == 'property' and len(menu['options']) == 2
    assert {option['unit_id'] for option in menu['options']} == {'van','oak'}
    second = menu['options'][1]['unit_id']
    mid, _ = next_input(lane, 'The second option. How many bathrooms does it have?')
    assert state(lane)['conversation_focus']['property_type_id'] == second
    assert 'get_unit_details' in tools_for(lane, mid)
    assert ('van buren' if second == 'van' else 'oakwood') in lane.calls[-1].casefold()
    assert re.search(r'\b(?:2|two)\s+bathrooms?\b', lane.calls[-1], re.I)
    assert lane.db.query(lane.Run).count() == 2
