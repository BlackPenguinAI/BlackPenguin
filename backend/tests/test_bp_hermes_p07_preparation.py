"""P07: published tool limits reach both isolated turn preparation entrypoints."""
from __future__ import annotations

from types import SimpleNamespace

from test_bp_hermes_p03_state import orm, db, SCOPE
from app.modules.hermes_sales_core.config import HermesSettings
from app.modules.hermes_sales_core.contracts import TurnResult


def test_p02_and_p04_prepare_accept_scoped_tool_policy_without_live_writes(orm, db, monkeypatch):
    from app.modules.hermes_sales_core import bp_turn, bp_p04_turn
    from app.modules.hermes_sales_core.bp_context import BPSnapshot
    snapshot = BPSnapshot(scope=SCOPE, channel='simulation',
                          company={'name':'A'}, project={'name':'P','timezone':'America/Lima'},
                          lead={'full_name':'Test Buyer'},
                          commercial={'confirmed_project_facts':{},'property_types':[],
                                      'inventory':[], 'catalog_coverage':{'exhaustive':False},
                                      'available_assets':[]})
    captured = []
    class FakeRuntime:
        def __init__(self, settings, port, **kwargs):
            captured.append(kwargs)
        def process_turn(self, request):
            return TurnResult(reply='Verified response only.', history=[], tool_observations=[])
    class FakePort:
        def __init__(self, *_args, **_kwargs):
            self.menus = []
    monkeypatch.setattr(bp_turn, 'HermesSalesRuntime', FakeRuntime)
    monkeypatch.setattr(bp_p04_turn, 'HermesSalesRuntime', FakeRuntime)
    monkeypatch.setattr(bp_turn, 'build_bp_snapshot', lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(bp_p04_turn, 'build_bp_snapshot', lambda *args, **kwargs: snapshot)
    policy = frozenset({'get_project_overview'})
    kwargs = dict(inbound_message_id='inbound-a', settings=HermesSettings(api_key='fake-test'))
    offline = bp_turn.prepare_offline_turn(db, SCOPE, **kwargs, enabled_tools=policy)
    p04 = bp_p04_turn.prepare_p04_simulation_turn(db, SCOPE, **kwargs,
                                                  enabled_tools=policy, port_factory=FakePort)
    assert offline.result.reply == p04.prepared.result.reply
    assert len(captured) == 2
    assert all(row['enabled_tools'] == policy for row in captured)
    assert not db.query(orm.models.HermesSalesStateEvent).count()
