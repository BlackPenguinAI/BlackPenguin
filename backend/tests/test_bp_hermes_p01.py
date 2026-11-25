"""P01 isolation regression. No network, SQL, Hermes installation or live providers.

These are contract tests; they do not claim to exercise a real OpenRouter response.
"""
from __future__ import annotations
import json
import sys
import types
from copy import deepcopy

import pytest

from app.modules.hermes_sales_core import (
    HermesSalesRuntime, HermesSettings, TurnScope, TurnRequest,
)
from app.modules.hermes_sales_core import contextual_choices as choices
from app.modules.hermes_sales_core.choice_state import (
    record_delivered_menu, resolve_visible_choice, clear_visible_choice,
)
from app.modules.hermes_sales_core.tool_schemas import SCHEMAS, TOOLSET, P01_DENIED_TOOLS


SCOPE = TurnScope(company_id='company-a', project_id='project-a', conversation_id='conversation-a', lead_id='lead-a')


class RecordingPort:
    def __init__(self):
        self.calls = []
    def invoke(self, name, arguments, scope):
        self.calls.append((name, dict(arguments), scope))
        return {'ok': True, 'source': 'offline_fixture', 'name': name}


@pytest.fixture
def fake_sdk(monkeypatch):
    """Fake ONLY the SDK's public usage surface from original v13.3.3."""
    registry_module = types.ModuleType('tools.registry')
    registry_module.registry = types.SimpleNamespace(handlers={}, schemas={})
    def register(*, name, toolset, schema, handler, check_fn):
        assert toolset == TOOLSET
        assert check_fn()
        registry_module.registry.handlers[name] = handler
        registry_module.registry.schemas[name] = schema
    registry_module.registry.register = register
    tools_module = types.ModuleType('tools')
    tools_module.__path__ = []
    run_agent_module = types.ModuleType('run_agent')
    calls = []
    class AIAgent:
        def __init__(self, **kwargs):
            calls.append(('constructor', kwargs))
            self.valid_tool_names = set(registry_module.registry.handlers)
        def run_conversation(self, user_payload, conversation_history, persist_user_message):
            calls.append(('run', user_payload, conversation_history, persist_user_message))
            return {'final_response': 'Available verified homes.\n\n1. Alpha\n2. Beta',
                    'messages': [{'role': 'user', 'content': persist_user_message},
                                 {'role': 'assistant', 'content': 'Available verified homes.'}]}
    run_agent_module.AIAgent = AIAgent
    monkeypatch.setitem(sys.modules, 'run_agent', run_agent_module)
    monkeypatch.setitem(sys.modules, 'tools', tools_module)
    monkeypatch.setitem(sys.modules, 'tools.registry', registry_module)
    return registry_module.registry, calls


def settings():
    return HermesSettings(api_key='offline-fake-test-key')


def request(message='show me available homes', **kwargs):
    return TurnRequest(scope=SCOPE, message=message, **kwargs)


def test_tool_names_and_effect_lock_are_explicit():
    assert len(SCHEMAS) == 15
    assert len(P01_DENIED_TOOLS) == 8
    assert {'search_properties', 'get_available_visit_slots', 'compare_properties'} <= set(SCHEMAS)
    assert {'book_onsite_visit', 'cancel_onsite_visit', 'reschedule_onsite_visit'} <= P01_DENIED_TOOLS
    assert all('description' in v and 'parameters' in v for v in SCHEMAS.values())


def test_settings_preserve_demo_sdk_defaults():
    config = settings()
    assert config.model == 'openai/gpt-4o-mini'
    assert 'offline-fake-test-key' not in repr(config)
    assert config.base_url == 'https://openrouter.ai/api/v1'
    assert config.max_iterations == 12
    assert 'ENGLISH' in config.effective_prompt
    assert 'another project' not in config.effective_prompt


def test_missing_key_and_insecure_settings_fail_closed():
    with pytest.raises(ValueError): HermesSettings(api_key='')
    with pytest.raises(ValueError): HermesSettings(api_key='x', max_iterations=99)
    with pytest.raises(ValueError): HermesSettings(api_key='x', base_url='https://attacker.invalid')


def test_scope_and_turn_validation():
    with pytest.raises(ValueError): TurnScope('', 'p', 'c', 'l')
    with pytest.raises(ValueError): TurnRequest(SCOPE, '  ')
    with pytest.raises(ValueError): TurnRequest(SCOPE, 'hi', channel='websocket')


def test_runtime_invokes_real_sdk_surface_without_persistence(fake_sdk):
    registry, calls = fake_sdk
    initial_history = [{'role':'assistant','content':'Hello!'}]
    result = HermesSalesRuntime(settings(), RecordingPort()).process_turn(
        request(history=deepcopy(initial_history), verified_context={'conversation_focus':{'unit_id':'H-201'}})
    )
    assert result.reply.startswith('Available verified homes.\n\n1.')
    assert len(result.history) == 2
    ctor = calls[0][1]
    assert ctor['model'] == 'openai/gpt-4o-mini'
    assert ctor['enabled_toolsets'] == [TOOLSET]
    assert ctor['disabled_toolsets'] == ['terminal','file','web','browser']
    assert ctor['skip_memory'] is True and ctor['skip_context_files'] is True
    assert ctor['save_trajectories'] is False
    assert ctor['max_iterations'] == 12 and ctor['tool_delay'] == 0
    assert len(registry.handlers) == 15
    assert 'company-a' in calls[1][1]
    assert 'H-201' in calls[1][1]
    assert calls[1][2] == initial_history
    assert calls[1][3] == 'show me available homes'


def test_read_tool_is_scoped_and_does_not_write(fake_sdk):
    registry, _ = fake_sdk
    port = RecordingPort()
    HermesSalesRuntime(settings(), port).process_turn(request())
    result = json.loads(registry.handlers['get_project_overview']({}))
    assert result['ok'] and result['source'] == 'offline_fixture'
    assert port.calls == [('get_project_overview', {}, SCOPE)]


@pytest.mark.parametrize('name', sorted(P01_DENIED_TOOLS))
def test_no_effect_tool_reaches_port_in_p01(fake_sdk, name):
    registry, _ = fake_sdk
    port = RecordingPort()
    HermesSalesRuntime(settings(), port).process_turn(request())
    response = json.loads(registry.handlers[name]({'unit_id':'H-201'}))
    assert response['error_code'] == 'P01_EFFECTS_DISABLED'
    assert port.calls == []


def test_duplicate_failed_tool_call_caches_rejection(fake_sdk):
    registry, _ = fake_sdk
    class Reject(RecordingPort):
        def invoke(self, name, arguments, scope):
            self.calls.append((name, dict(arguments), scope))
            return {'error':'catalog temporarily unavailable'}
    port = Reject()
    HermesSalesRuntime(settings(), port).process_turn(request())
    handler = registry.handlers['search_properties']
    assert json.loads(handler({'scope':'temporary'}))['error_code'] == 'DOMAIN_VALIDATION_REJECTED'
    assert json.loads(handler({'scope':'temporary'}))['already_checked'] is True
    assert len(port.calls) == 1


def test_scope_mismatch_does_not_reach_llm(fake_sdk):
    _, calls = fake_sdk
    with pytest.raises(ValueError, match='mismatched'):
        HermesSalesRuntime(settings(), RecordingPort()).process_turn(request(verified_context={
            'scope':{'company_id':'company-b','project_id':'project-a','conversation_id':'conversation-a','lead_id':'lead-a'}
        }))
    assert len([c for c in calls if c[0] == 'run']) == 0


def test_contextual_second_day_overrides_legacy_property_choice():
    dates = {'ok':True, 'unit_id':'H-201', 'timezone':'America/Lima', 'available_dates':[
        {'date':'2026-12-01'}, {'date':'2026-12-02'}, {'date':'2026-12-03'}]}
    menu = choices.choice_from_slots(dates)
    state = {'visit_draft':{'unit_id':'H-201','status':'day_needed'},
             'last_presented_property_options':{'options':[{'display_number':2,'unit_id':'H-101'}]}}
    recorded = record_delivered_menu(state, menu=menu, outbound_message_id='out-msg-1')
    assert recorded['source_reply_message_id'] == 'out-msg-1'
    assert '2. Wednesday, December 2' in choices.render_menu(menu)
    for expression in ('2','Option 2','the second option','la segunda'):
        picked = resolve_visible_choice(state, expression)
        assert picked and picked['type'] == 'visit_day'
        assert picked['choice']['date'] == '2026-12-02'
        assert picked['unit_id'] == 'H-201'
    clear_visible_choice(state)
    assert resolve_visible_choice(state, 'option 2') is None


def test_time_menu_keeps_verified_proposal_and_never_books():
    menu = choices.choice_from_slots({'ok':True,'unit_id':'H-201','date':'2026-12-02',
        'proposal_id':'proposal-synthetic','timezone':'America/Lima', 'available_slots':[
            {'date':'2026-12-02','start_time':'09:00'},
            {'date':'2026-12-02','start_time':'10:00'}]})
    state = {'visit_draft':{'unit_id':'H-201','date':'2026-12-02','status':'hour_needed'}}
    record_delivered_menu(state, menu=menu, outbound_message_id='out-msg-2')
    selected = resolve_visible_choice(state, 'the second option')
    assert selected['type'] == 'visit_time'
    assert selected['choice']['start_time'] == '10:00'
    assert selected['choice']['proposal_id'] == 'proposal-synthetic'
    assert not state.get('booked_visits')


def test_media_choice_uses_verified_menu_and_outbound_message():
    menu = choices.media_menu('Would you like photos or the PDF fact sheet?', unit_id='H-201',
         media={'gallery_url':'/properties/H-201/gallery', 'documents':[{'type':'fact_sheet','url':'/demo-assets/H201.pdf'}]})
    assert menu is not None
    state = {'visit_draft':{'unit_id':None,'status':'idle'}}
    record_delivered_menu(state, menu=menu, outbound_message_id='out-msg-3')
    assert resolve_visible_choice(state, 'Option 2')['choice']['kind'] == 'documents'


def test_no_nonvisible_choice_can_be_recorded():
    with pytest.raises(ValueError):
        record_delivered_menu({}, menu={'type':'visit_day','options':[{'date':'2026-12-01'}]}, outbound_message_id='m1')
    with pytest.raises(ValueError):
        record_delivered_menu({}, menu={'type':'visit_day','options':[{},{}]}, outbound_message_id='')
