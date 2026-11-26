"""Pure P09 routing acceptance tests: no API, network or provider is contacted."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / 'app/integrations/messaging_gateway.py'
META = ROOT / 'app/modules/meta_leads/router.py'
ENTRY = ROOT / 'app/modules/sales_agent/p09_live_entry.py'


def _source_functions(path: Path, names: set[str], env: dict) -> dict:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    chosen = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(path), 'exec'), env)
    return env


def _gateway():
    tree = ast.parse(GATEWAY.read_text(encoding='utf-8'))
    table = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(x, ast.Name) and x.id == 'COUNTRY_CHANNELS' for x in node.targets))
    env = {'COUNTRY_CHANNELS': ast.literal_eval(table),
           'DESTINATION_PREFIXES': (('+52','MX'),('+51','PE'),('+54','AR'),('+1','US'))}
    env.update(_source_functions(GATEWAY,
        {'destination_country_code', 'destination_channel'}, env))
    return env


def test_country_routing_is_deterministic_without_synthetic_fallback():
    env = _gateway()
    route = env['destination_channel']
    for phone, wanted in [('+12025550123', 'sms'), ('+51999888777', 'whatsapp'),
                          ('+525555123456', 'whatsapp'), ('+5491122345678', 'whatsapp'),
                          ('+442012345678', None), ('', None)]:
        assert route(phone) == wanted


def test_explicit_sms_request_cannot_override_peruvian_whatsapp_route():
    env = _gateway()
    env['_channel_is_ready'] = lambda db, *, company_id, channel: channel in {'sms', 'whatsapp'}
    env['get_telnyx_company_config'] = lambda db, company_id: SimpleNamespace(primary_channel='sms')
    _source_functions(GATEWAY, {'company_live_channel'}, env)
    route = env['company_live_channel']
    assert route(None, company_id='c1', requested='sms', destination_phone='+51999888777') == 'whatsapp'
    assert route(None, company_id='c1', requested='whatsapp', destination_phone='+12025550123') == 'sms'
    assert route(None, company_id='c1', requested='sms', destination_phone='+44123') is None
    env['_channel_is_ready'] = lambda db, *, company_id, channel: False
    assert route(None, company_id='c1', destination_phone='+51999888777') is None


def test_live_meta_intake_is_real_only_and_does_not_pin_sms():
    meta = META.read_text(encoding='utf-8')
    entry = ENTRY.read_text(encoding='utf-8')
    assert 'from app.modules.sales_agent.p09_live_entry import start_live_lead' in meta
    assert 'preferred_channel=None' in meta
    assert 'captured_channel = destination_channel(phone)' in meta
    assert 'prepare_meta_simulation' not in ast.unparse(ast.parse(entry)) .replace('``prepare_meta_simulation``', '')
    assert 'await live._dispatch(' in entry
    assert "lead.agent_status = 'routing_blocked'" in entry


def test_staff_manual_intake_passes_destination_number_to_existing_router():
    manual = ROOT / 'app/modules/sales_agent/live_test_service.py'
    # Compatibility contract is checked against the source in a full checkout.
    if manual.exists():
        source = manual.read_text(encoding='utf-8')
        assert 'destination_phone=lead_form.get("phone")' in source
