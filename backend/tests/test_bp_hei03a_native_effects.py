"""HEI-03A gateway tests using HEI-01B's SQLite fixture and P04 seam.

No real SDK, scheduling, share service, provider or production DB is invoked.
The new gateway, ORM transaction, existing router and staged receipt are real;
P04's service boundary is a deterministic SQL-writing double.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4
import importlib.util
import sys

import pytest
from sqlalchemy import Column, Integer, JSON, String
from sqlalchemy.orm import declarative_base

from test_bp_hei01b_staged_runtime import unit, run


@pytest.fixture
def native(unit, monkeypatch):
    u = unit
    package = sys.modules[u.staged.__package__]
    root = Path(__file__).resolve().parents[1] / 'app' / 'modules' / 'hermes_sales_core'
    base = declarative_base()
    class State(base):
        __tablename__ = 'native_test_state'
        id = Column(String, primary_key=True)
        revision = Column(Integer)
        data = Column(JSON)
    class Operation(base):
        __tablename__ = 'native_test_operation'
        id = Column(String, primary_key=True, default=lambda: str(uuid4()))
        company_id = Column(String)
        project_id = Column(String)
        conversation_id = Column(String)
        lead_id = Column(String)
        inbound_message_id = Column(String)
        request_id = Column(String)
        operation_type = Column(String)
        status = Column(String)
        result_json = Column(JSON)
    base.metadata.create_all(u.db.get_bind())
    def install(name, **attrs):
        mod = ModuleType(package.__name__ + '.' + name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        monkeypatch.setattr(package, name, mod, raising=False)
        return mod
    def load(db, scope):
        row = db.get(State, scope.conversation_id, populate_existing=True)
        return SimpleNamespace(revision=row.revision, data=deepcopy(row.data))
    install('bp_state_store', load=load)
    install('bp_operation_models', HermesSalesOperation=Operation)
    calls = []
    flags = SimpleNamespace(fail=False, bad_receipt=False, bad_revision=False, bad_result=False, held=False)
    def execute(db, scope, *, expected_revision, inbound_message_id, asset_id=None):
        calls.append((scope, expected_revision, inbound_message_id, asset_id))
        row = db.get(State, scope.conversation_id)
        data = deepcopy(row.data)
        candidate = mod.pending_effect(data, inbound_message_id)
        kind = candidate['kind']
        result = {'status': mod.STATUSES[kind], 'calendar_status': 'simulation', 'meeting_id': 'meeting-1',
                  'booking_operation_id': 'book-op', 'cancellation_operation_id': 'cancel-op',
                  'original_meeting_id': 'old-meeting', 'reschedule_operation_id': 'reschedule-op'}
        if kind == 'material':
            assert asset_id == candidate['asset_id']
            result = {'status': mod.STATUSES[kind], 'asset_id': asset_id,
                      'share_id': 'share-1', 'delivery': 'not_sent'}
        op = Operation(**scope.__dict__, inbound_message_id=inbound_message_id,
            request_id=candidate['request_id'], operation_type=kind,
            status='failed' if flags.bad_receipt else 'completed', result_json=result)
        # Exercise rollback even when a nested P04-style savepoint has flushed.
        with db.begin_nested():
            db.add(op)
            row.revision += 2 if flags.bad_revision else 1
            row.data = {}
            db.flush()
        if flags.fail:
            raise RuntimeError('simulated native failure')
        if flags.bad_result:
            return {**result, 'status': 'unknown'}
        return {**result, 'replayed': False, 'url': 'https://example.invalid/private-bearer-token'}
    install('bp_effect_executor', execute_p04_simulation_operation=execute)
    spec = importlib.util.spec_from_file_location(package.__name__ + '.native_effects', root / 'native_effects.py')
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    monkeypatch.setattr(package, 'native_effects', mod, raising=False)
    spec.loader.exec_module(mod)
    def policy(*args):
        if flags.held:
            raise mod.NativeEffectError('The current business policy requires human review.')
    monkeypatch.setattr(mod, '_assert_business_policy', policy)
    # Extend the old fixture's intentionally tiny tool registry for this suite.
    allowed = frozenset(set(u.staff.ALL_TOOLS) | set(mod.TOOLS.values()))
    monkeypatch.setattr(u.staff, 'ALL_TOOLS', allowed)
    monkeypatch.setattr(u.staff, 'VISIBLE_TOOLS', sorted(allowed))
    u.publish(enabled_tools=sorted(allowed))
    def setup(kind='book', *, tool=True, multiple=False):
        out = run(u, event='hermes:staged:native-' + str(uuid4()), message='A buyer test request')
        inbound = out['inbound_message_id']
        data = {}
        if kind == 'material':
            data['offered_assets'] = {'pending_request': {'id': 'req-1', 'unit_id': 'type-a',
                'source_inbound_message_id': inbound, 'asset_ids': ['asset-a', 'asset-b'] if multiple else ['asset-a']}}
        elif kind:
            data['confirmation_request'] = {'id': 'req-1', 'kind': kind, 'status': 'execution_requested',
                'confirmed_inbound_message_id': inbound, 'unit_id': 'type-a', 'date': '2027-01-01',
                'start_time': '10:00', 'timezone': 'America/Lima'}
        row = u.db.get(u.Run, out['run_id'])
        if kind and tool:
            row.output_snapshot = {**row.output_snapshot,
                'tool_observations': [{'tool': mod.TOOLS[kind], 'status': 'executed'}]}
        u.db.add(State(id=u.scope.conversation_id, revision=out['state_revision'], data=data))
        u.db.commit()
        return out
    yield SimpleNamespace(u=u, mod=mod, State=State, Operation=Operation, setup=setup,
                          calls=calls, flags=flags, allowed=allowed)


def effect(n, out):
    return n.mod.execute_native_effect(n.u.db, n.u.scope, inbound_message_id=out['inbound_message_id'])


@pytest.mark.parametrize('kind', ['book', 'cancel', 'reschedule', 'material'])
def test_native_receipt_and_replay(native, kind):
    n = native
    out = n.setup(kind)
    receipt = effect(n, out)
    assert receipt['kind'] == kind and receipt['external_effects'] is False
    assert receipt['delivery'] == 'in_app_only' and receipt['state_revision'] == 2
    assert n.u.db.query(n.Operation).count() == 1
    assert n.u.db.query(n.u.Message).count() == 3
    message = n.u.db.get(n.u.Message, receipt['receipt_message_id'])
    assert message.metadata_json['native_operation_id'] == receipt['operation_id']
    assert 'private-bearer-token' not in str(receipt) + message.content
    if kind == 'material':
        assert receipt['material_delivery'] == 'not_sent' and 'No document has been sent' in message.content
    else:
        assert 'simulation' in message.content and 'No external calendar' in message.content
    # Replay the original conversation turn and then replay the native effect.
    original = n.u.staged.execute_isolated_turn(n.u.db, n.u.scope, inbound_message_id=out['inbound_message_id'])
    assert original['replayed'] and original['message_id'] == out['message_id']
    replay = effect(n, out)
    assert replay['replayed'] and replay['operation_id'] == receipt['operation_id']
    assert len(n.calls) == 1 and n.u.db.query(n.u.Message).count() == 3


def test_no_prepared_operation_is_a_noop(native):
    out = native.setup(None)
    assert effect(native, out)['status'] == 'no_effect_requested'
    assert not native.calls


def test_no_executed_tool_observation_blocks_effect(native):
    out = native.setup(tool=False)
    with pytest.raises(native.mod.NativeEffectError, match='tool policies'):
        effect(native, out)
    assert not native.calls


def test_disabled_current_policy_blocks_new_effect(native):
    out = native.setup()
    native.u.publish(enabled=False, enabled_tools=sorted(native.allowed))
    with pytest.raises(native.mod.NativeEffectError, match='tool policies'):
        effect(native, out)
    assert not native.calls


def test_revoked_tool_blocks_new_effect(native):
    out = native.setup()
    native.u.publish(enabled_tools=['get_project_overview'])
    with pytest.raises(native.mod.NativeEffectError, match='tool policies'):
        effect(native, out)
    assert not native.calls


def test_compliance_hold_blocks_effect(native):
    out = native.setup()
    native.flags.held = True
    with pytest.raises(native.mod.NativeEffectError, match='human review'):
        effect(native, out)
    assert not native.calls


def test_stale_state_blocks_effect(native):
    out = native.setup()
    native.u.db.get(native.State, native.u.scope.conversation_id).revision += 1
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='newer state'):
        effect(native, out)
    assert not native.calls


def test_intervening_inbound_blocks_effect(native):
    out = native.setup()
    original = native.u.db.get(native.u.Message, out['message_id'])
    native.u.db.add(native.u.Message(conversation_id=native.u.scope.conversation_id,
        channel='simulation', direction='inbound', role='user', status='received', content='Wait',
        created_at=original.created_at + timedelta(seconds=1), metadata_json={'lead_id':native.u.scope.lead_id}))
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='latest delivered'):
        effect(native, out)
    assert not native.calls


@pytest.mark.parametrize('flag', ['fail', 'bad_receipt', 'bad_revision', 'bad_result'])
def test_failed_effect_rolls_back_native_writes(native, flag):
    out = native.setup()
    setattr(native.flags, flag, True)
    with pytest.raises((RuntimeError, native.mod.NativeEffectError)):
        effect(native, out)
    assert native.u.db.query(native.Operation).count() == 0
    assert native.u.db.query(native.u.Message).count() == 2
    assert native.u.db.get(native.State, native.u.scope.conversation_id).revision == 1
    assert 'native_effect' not in native.u.db.get(native.u.Run, out['run_id']).output_snapshot
    setattr(native.flags, flag, False)
    assert effect(native, out)['status'] == 'confirmed'


def test_multi_asset_is_not_silently_reduced(native):
    out = native.setup('material', multiple=True)
    with pytest.raises(native.mod.NativeEffectError, match='Single verified material'):
        effect(native, out)
    assert not native.calls


def test_forged_pin_is_rejected(native):
    out = native.setup()
    row = native.u.db.get(native.u.Run, out['run_id'])
    inbound = native.u.db.get(native.u.Message, out['inbound_message_id'])
    bad = {**inbound.metadata_json['sales_engine_pin'], 'lead_id': 'foreign-lead'}
    row.input_snapshot = {**row.input_snapshot, 'sales_engine_pin': bad}
    inbound.metadata_json = {**inbound.metadata_json, 'sales_engine_pin': bad}
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='pinned isolated'):
        effect(native, out)
    assert not native.calls


def test_noncompleted_run_blocks_effect(native):
    out = native.setup()
    native.u.db.get(native.u.Run, out['run_id']).status = 'failed'
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='completed'):
        effect(native, out)
    assert not native.calls


def test_receipt_tampering_fails_closed(native):
    out = native.setup()
    receipt = effect(native, out)
    native.u.db.get(native.u.Message, receipt['receipt_message_id']).content = 'forged'
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='Inconsistent'):
        effect(native, out)
    assert len(native.calls) == 1


def test_production_environment_refuses_before_effect(native, monkeypatch):
    out = native.setup()
    monkeypatch.setenv('ENVIRONMENT', 'production')
    with pytest.raises(native.u.staged.StagedRuntimeError):
        effect(native, out)
    assert not native.calls


def test_opt_out_refuses_before_effect(native):
    out = native.setup()
    native.u.db.get(native.u.Lead, native.u.scope.lead_id).is_opt_out = True
    native.u.db.commit()
    with pytest.raises(native.u.staged.StagedRuntimeError):
        effect(native, out)
    assert not native.calls


def test_pending_reply_never_reports_success(native):
    out = native.setup()
    state = native.u.db.get(native.State, native.u.scope.conversation_id).data
    text = native.mod.pending_reply(state, out['inbound_message_id'], 'Your visit is confirmed!')
    assert 'not booked yet' in text
    assert native.mod.pending_reply(state, 'different', 'Unrelated property question') == 'Unrelated property question'


def test_conflicting_effects_rejected(native):
    out = native.setup()
    row = native.u.db.get(native.State, native.u.scope.conversation_id)
    row.data = {**row.data, 'offered_assets': {'pending_request': {'id': 'req-2',
        'source_inbound_message_id': out['inbound_message_id'], 'asset_ids': ['asset-a']}}}
    native.u.db.commit()
    with pytest.raises(native.mod.NativeEffectError, match='Multiple simultaneous'):
        effect(native, out)
    assert not native.calls
