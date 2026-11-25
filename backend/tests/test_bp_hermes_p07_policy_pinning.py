"""P07 published policy consistency: one turn gets one immutable Staff snapshot."""
from __future__ import annotations

import pytest

from test_bp_hermes_p05_global import unit, registry


def test_turn_pins_one_global_model_prompt_and_tool_allowlist(unit, registry, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'isolated-placeholder-not-live')
    first = unit.control.baseline()
    first.update(enabled=True, enabled_tools=['get_project_overview'], max_iterations=3)
    saved = unit.control.create_draft(registry, configuration=first,
                                      note='P07 pinned policy', actor_id='staff-a')
    unit.control.publish(registry, version_id=saved['id'], actor_id='staff-a')
    settings, version_id, enabled = unit.control.settings_for_turn(registry)
    assert version_id == saved['id']
    assert enabled == frozenset({'get_project_overview'})
    assert settings.max_iterations == 3
    assert 'isolated-placeholder-not-live' not in repr(settings)
    original_prompt = settings.effective_prompt

    # Publishing another global version cannot change an in-flight turn's
    # already-frozen settings, prompt or allowed tools.
    second = unit.control.baseline()
    second.update(enabled=True, enabled_tools=['search_properties'], max_iterations=9,
                  system_prompt=original_prompt + '\nBe concise about verified inventory.')
    newer = unit.control.create_draft(registry, configuration=second,
                                      note='P07 newer version', actor_id='staff-a')
    unit.control.publish(registry, version_id=newer['id'], actor_id='staff-a')
    assert enabled == frozenset({'get_project_overview'})
    assert settings.effective_prompt == original_prompt
    assert settings.max_iterations == 3
    settings_next, id_next, tools_next = unit.control.settings_for_turn(registry)
    assert id_next == newer['id'] and id_next != version_id
    assert tools_next == frozenset({'search_properties'})
    assert settings_next.max_iterations == 9


def test_missing_secret_causes_no_fallback_for_enabled_global_runtime(unit, registry, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    cfg = unit.control.baseline()
    cfg['enabled'] = True
    version = unit.control.create_draft(registry, configuration=cfg,
                                        note='P07 missing key', actor_id='staff-a')
    unit.control.publish(registry, version_id=version['id'], actor_id='staff-a')
    with pytest.raises(ValueError, match='OPENROUTER_API_KEY'):
        unit.control.settings_for_turn(registry)
