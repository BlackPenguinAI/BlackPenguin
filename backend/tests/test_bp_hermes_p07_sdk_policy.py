"""P07: verify Staff tool restrictions at the Hermes SDK boundary.

No network, API key, HTTP, filesystem tool or provider effect is used. The
fake SDK models the public registry.check_fn contract; all effect handlers are
still challenged directly in case a future SDK bypasses tool discovery.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from app.modules.hermes_sales_core.config import HermesSettings
from app.modules.hermes_sales_core.contracts import TurnRequest, TurnScope
from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
from app.modules.hermes_sales_core.tool_schemas import SCHEMAS, TOOLSET

SCOPE = TurnScope('company-a', 'project-a', 'conversation-a', 'lead-a')


class RecordingPort:
    def __init__(self):
        self.calls = []

    def invoke(self, name, arguments, scope):
        self.calls.append((name, arguments, scope))
        return {'ok': True, 'tool': name}


@pytest.fixture
def sdk(monkeypatch):
    registry = types.SimpleNamespace(entries={}, calls=[], forced_exposure=None, toolset_check=None)

    def register(*, name, toolset, schema, handler, check_fn):
        assert toolset == TOOLSET
        if registry.toolset_check is None:
            registry.toolset_check = check_fn  # pinned SDK caches FIRST tool check
        registry.entries[name] = (schema, handler, check_fn)
    registry.register = register
    def get_entry(name):
        return types.SimpleNamespace(toolset=TOOLSET) if name in registry.entries else None
    registry.get_entry = get_entry
    def deregister(name):
        registry.entries.pop(name, None)
        if not registry.entries:
            registry.toolset_check = None
    registry.deregister = deregister
    module = types.ModuleType('tools.registry')
    module.registry = registry
    tools = types.ModuleType('tools')
    tools.__path__ = []
    agent_module = types.ModuleType('run_agent')

    class FakeAgent:
        def __init__(self, **kwargs):
            registry.calls.append(('init', kwargs))
            self.valid_tool_names = (registry.forced_exposure if registry.forced_exposure is not None
                                     else {name for name, item in registry.entries.items() if
                                           registry.toolset_check() and item[2]()})

        def run_conversation(self, prompt, conversation_history, persist_user_message):
            registry.calls.append(('run', persist_user_message))
            return {'final_response': 'Verified options are available.', 'messages': []}

    agent_module.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, 'tools', tools)
    monkeypatch.setitem(sys.modules, 'tools.registry', module)
    monkeypatch.setitem(sys.modules, 'run_agent', agent_module)
    return registry


def _turn(runtime):
    return runtime.process_turn(TurnRequest(SCOPE, 'Show me homes', channel='simulation'))


def test_disabled_tool_not_exposed_or_executed_even_if_called_directly(sdk):
    port = RecordingPort()
    selected = frozenset({'search_properties', 'get_project_overview'})
    result = _turn(HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), port,
                                      enabled_tools=selected))
    assert result.reply
    assert sdk.entries['search_properties'][2]() is True
    assert sdk.entries['book_onsite_visit'][2]() is False
    assert set(name for name, row in sdk.entries.items() if row[2]()) == selected
    blocked = json.loads(sdk.entries['book_onsite_visit'][1]({'unit_id': 'unit-a'}))
    assert blocked['error_code'] == 'GLOBAL_TOOL_DISABLED'
    assert not port.calls
    allowed = json.loads(sdk.entries['search_properties'][1]({'scope': 'temporary'}))
    assert allowed['ok'] and port.calls == [('search_properties', {'scope': 'temporary'}, SCOPE)]


def test_sdk_cannot_silently_ignore_global_tool_filter(sdk):
    sdk.forced_exposure = set(SCHEMAS)
    port = RecordingPort()
    with pytest.raises(RuntimeError, match='tool allowlist mismatch'):
        _turn(HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), port,
                                  enabled_tools=frozenset({'search_properties'})))
    assert not [call for call in sdk.calls if call[0] == 'run']
    assert not port.calls


def test_policy_switch_cannot_leave_stale_registered_access(sdk):
    port = RecordingPort()
    settings = HermesSettings(api_key='fake-not-live')
    _turn(HermesSalesRuntime(settings, port, enabled_tools=frozenset({'get_project_overview'})))
    assert sdk.entries['get_project_overview'][2]() is True
    _turn(HermesSalesRuntime(settings, port, enabled_tools=frozenset({'search_properties'})))
    assert sdk.entries['get_project_overview'][2]() is False
    result = json.loads(sdk.entries['get_project_overview'][1]({}))
    assert result['error_code'] == 'GLOBAL_TOOL_DISABLED'
    assert not port.calls


def test_explicit_zero_tool_policy_disables_every_business_tool(sdk):
    port = RecordingPort()
    _turn(HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), port,
                             enabled_tools=frozenset()))
    assert all(not row[2]() for row in sdk.entries.values())
    assert json.loads(sdk.entries['search_properties'][1]({}))['error_code'] == 'GLOBAL_TOOL_DISABLED'
    assert not port.calls


def test_unknown_and_malformed_tools_fail_before_sdk_import(sdk):
    with pytest.raises(ValueError, match='unknown tool'):
        HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), RecordingPort(),
                           enabled_tools=frozenset({'terminal'}))
    with pytest.raises(ValueError, match='collection'):
        HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), RecordingPort(),
                           enabled_tools='search_properties')
    assert sdk.calls == []


def test_previous_p01_p04_callers_remain_default_compatible(sdk):
    port = RecordingPort()
    _turn(HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), port))
    assert all(row[2]() for row in sdk.entries.values())
    # Tool exposure is not the same as effect authorization.
    rejected = json.loads(sdk.entries['book_onsite_visit'][1]({}))
    assert rejected['error_code'] == 'P01_EFFECTS_DISABLED'
    assert not port.calls


def test_pinned_sdk_first_toolset_check_recovers_after_empty_policy(sdk):
    port = RecordingPort()
    settings = HermesSettings(api_key='fake-not-live')
    _turn(HermesSalesRuntime(settings, port, enabled_tools=frozenset()))
    assert sdk.toolset_check() is False
    _turn(HermesSalesRuntime(settings, port, enabled_tools=frozenset({'get_project_overview'})))
    assert sdk.toolset_check() is True
    assert [name for name, entry in sdk.entries.items() if entry[2]()] == ['get_project_overview']
    assert not port.calls


def test_preexisting_foreign_tool_name_fails_closed(sdk):
    original = sdk.get_entry
    sdk.get_entry = lambda name: (types.SimpleNamespace(toolset='foreign-toolset')
                                  if name == 'search_properties' else original(name))
    with pytest.raises(RuntimeError, match='collides'):
        _turn(HermesSalesRuntime(HermesSettings(api_key='fake-not-live'), RecordingPort()))
    assert not sdk.calls
