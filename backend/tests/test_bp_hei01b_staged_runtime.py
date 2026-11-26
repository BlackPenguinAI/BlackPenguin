"""HEI-01B tests: real router, P05 registry and P08 receipt transaction.

SQLite ORM stand-ins and a fake P04 prepare/receipt seam replace full business
services and AIAgent. No real SDK, PostgreSQL locks, provider sends or bookings.
The isolated image smoke and real staging model journey are distinct gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4
import importlib.util
import sys

import pytest
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'modules'


@pytest.fixture
def unit(monkeypatch, tmp_path):
    base = declarative_base()
    engine = create_engine('sqlite:///:memory:')
    factory = sessionmaker(bind=engine, autoflush=False)
    def module(name, **attrs):
        obj = ModuleType(name)
        obj.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, obj)
        return obj
    def package(name, path):
        return module(name, __path__=[str(path)])
    def load(pkg, filename):
        name = pkg.__name__ + '.' + filename
        spec = importlib.util.spec_from_file_location(name, Path(pkg.__path__[0]) / (filename + '.py'))
        obj = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, obj)
        setattr(pkg, filename, obj)
        spec.loader.exec_module(obj)
        return obj
    def uid():
        return str(uuid4())
    class User(base):
        __tablename__ = 'users'
        id = Column(String, primary_key=True)
    class Lead(base):
        __tablename__ = 'leads'
        id = Column(String, primary_key=True)
        company_id = Column(String)
        project_id = Column(String)
        is_demo = Column(Boolean, default=True)
        is_opt_out = Column(Boolean, default=False)
        deleted_at = Column(DateTime)
        consent_status = Column(String, default='granted_simulation')
        agent_status = Column(String, default='active')
    class Conversation(base):
        __tablename__ = 'sales_conversations'
        id = Column(String, primary_key=True)
        company_id = Column(String)
        project_id = Column(String)
        lead_id = Column(String)
        channel = Column(String, default='simulation')
        is_paused = Column(Boolean, default=False)
    class Context(base):
        __tablename__ = 'sales_conversation_lead_contexts'
        id = Column(String, primary_key=True, default=uid)
        conversation_id = Column(String)
        lead_id = Column(String)
        is_active = Column(Boolean, default=True)
        activated_at = Column(DateTime)
    class Message(base):
        __tablename__ = 'sales_messages'
        __table_args__ = (UniqueConstraint('channel', 'provider_message_id'),)
        id = Column(String, primary_key=True, default=uid)
        conversation_id = Column(String)
        channel = Column(String)
        direction = Column(String)
        role = Column(String)
        status = Column(String)
        content = Column(Text)
        provider_message_id = Column(String)
        metadata_json = Column(JSON, default=dict)
        created_at = Column(DateTime, default=datetime.utcnow)
    class Run(base):
        __tablename__ = 'agent_runs'
        id = Column(String, primary_key=True, default=uid)
        conversation_id = Column(String)
        event_id = Column(String, unique=True)
        mode = Column(String)
        status = Column(String)
        graph_version = Column(String)
        toolset_version = Column(String)
        model = Column(String)
        prompt_configuration_id = Column(String)
        prompt_snapshot = Column(JSON)
        input_snapshot = Column(JSON)
        output_snapshot = Column(JSON)
        error_code = Column(String)
        completed_at = Column(DateTime)
    class Receipt(base):
        __tablename__ = 'hermes_sales_state_events'
        id = Column(String, primary_key=True, default=uid)
        conversation_id = Column(String)
        lead_id = Column(String)
        event_key = Column(String, unique=True)
        event_type = Column(String)
        revision = Column(Integer)
    module('app.db.postgres', Base=base)
    root = package('_hei01b_fixture', ROOT)
    hp = package(root.__name__ + '.hermes_sales_core', ROOT / 'hermes_sales_core')
    sp = package(root.__name__ + '.sales_agent', ROOT / 'sales_agent')
    selection = load(hp, 'engine_selection')
    monkeypatch.setitem(sys.modules, 'app.modules.hermes_sales_core.engine_selection', selection)
    config = load(hp, 'config')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Use only approved facts and keep conversation continuity. ' * 4)
    monkeypatch.setattr(config, 'PROMPT_PATH', prompt)
    hp.tool_schemas = module(hp.__name__ + '.tool_schemas', SCHEMAS={'get_project_overview': {}, 'search_properties': {}})
    load(hp, 'staff_models')
    staff = load(hp, 'staff_config')
    contracts = load(hp, 'contracts')
    scope = contracts.TurnScope('company-a', 'project-a', 'conv-a', 'lead-a')
    sp.models = module(sp.__name__ + '.models', SalesConversation=Conversation,
        SalesConversationLeadContext=Context, SalesMessage=Message, AgentRun=Run)
    monkeypatch.setitem(sys.modules, 'app.modules.sales_agent.models', sp.models)
    scoped = load(sp, 'conversation_scope')
    monkeypatch.setitem(sys.modules, 'app.modules.sales_agent.conversation_scope', scoped)
    router = load(sp, 'engine_router')
    monkeypatch.setitem(sys.modules, 'app.modules.sales_agent.engine_router', router)
    def require_scoped_entities(db, requested):
        c = db.get(Conversation, requested.conversation_id)
        lead = db.get(Lead, requested.lead_id)
        if (not c or not lead or lead.deleted_at or
                (c.company_id, c.project_id, c.lead_id) != (requested.company_id, requested.project_id, requested.lead_id) or
                (lead.company_id, lead.project_id) != (requested.company_id, requested.project_id)):
            raise PermissionError('Scope mismatch')
        return None, None, lead, c
    hp.bp_context = module(hp.__name__ + '.bp_context', require_scoped_entities=require_scoped_entities)
    hp.bp_models = module(hp.__name__ + '.bp_models', HermesSalesStateEvent=Receipt)
    calls = []
    behavior = SimpleNamespace(fail=False, fail_commit=False)
    def prepare(db, scope, *, inbound_message_id, settings, enabled_tools):
        calls.append((settings.effective_prompt, settings.model, enabled_tools))
        if behavior.fail:
            raise RuntimeError('Fake SDK failure')
        return SimpleNamespace(prepared=SimpleNamespace(inbound_message_id=inbound_message_id, scope=scope,
            result=contracts.TurnResult('1. Van Buren\n2. Monroe', [], [
                {'tool': 'search_properties', 'status': 'executed', 'arguments': {'secret': 'not-for-trace'}},
                {'tool': 'terminal', 'status': 'executed'},
                {'tool': 'get_project_overview', 'status': 'rejected', 'error_code': 'DOMAIN_VALIDATION_REJECTED'},
            ])))
    def commit(db, prepared, *, outbound_message_id):
        if behavior.fail_commit:
            raise RuntimeError('Fake receipt failure')
        inner = prepared.prepared
        out = db.get(Message, outbound_message_id)
        assert out.content == inner.result.reply
        revision = db.query(Receipt).count() + 1
        db.add(Receipt(conversation_id=inner.scope.conversation_id, lead_id=inner.scope.lead_id,
            event_key='hermes:sim:' + inner.inbound_message_id, event_type='simulation_receipt', revision=revision))
        db.flush()
        return SimpleNamespace(revision=revision)
    hp.bp_p04_turn = module(hp.__name__ + '.bp_p04_turn', prepare_p04_simulation_turn=prepare, commit_p04_simulation_receipt=commit)
    load(hp, 'p08_simulation')
    staged = load(hp, 'staged_runtime')
    monkeypatch.setenv('ENVIRONMENT', 'test')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fixture-secret')
    base.metadata.create_all(engine)
    db = factory()
    db.add_all([User(id='staff-a'), Lead(id=scope.lead_id, company_id=scope.company_id, project_id=scope.project_id),
                Conversation(id=scope.conversation_id, company_id=scope.company_id, project_id=scope.project_id, lead_id=scope.lead_id)])
    db.commit()
    def publish(**changes):
        policy = staff.baseline()
        policy.update({'enabled': True, **changes})
        draft = staff.create_draft(db, configuration=policy, note='test', actor_id='staff-a')
        staff.publish(db, version_id=draft['id'], actor_id='staff-a')
        return draft['id']
    version = publish()
    yield SimpleNamespace(db=db, staff=staff, selection=selection, router=router, staged=staged,
        scope=scope, version=version, publish=publish, Message=Message, Run=Run, Receipt=Receipt,
        Conversation=Conversation, Context=Context, Lead=Lead, calls=calls, behavior=behavior)
    db.close()
    engine.dispose()


def run(u, event='hermes:staged:01', message='Show me houses'):
    return u.staged.execute_isolated_turn(u.db, u.scope, event_id=event, message=message)


def test_new_turn_persists_exact_identity_and_receipt(unit):
    u = unit
    result = run(u)
    assert result['engine'] == 'hermes' and result['delivery'] == 'in_app_only'
    assert result['reply'] == '1. Van Buren\n2. Monroe'
    assert result['published_version_id'] == u.version
    row = u.db.get(u.Run, result['run_id'])
    assert row.status == 'completed' and row.graph_version == 'hermes/hei-01b'
    assert row.prompt_configuration_id == u.version
    inbound, outbound = [u.db.get(u.Message, result[k]) for k in ('inbound_message_id', 'message_id')]
    assert inbound.metadata_json['sales_engine_pin']['engine'] == 'hermes'
    assert outbound.metadata_json['agent_run_id'] == row.id
    assert u.db.query(u.Receipt).count() == 1
    assert len(row.output_snapshot['tool_observations']) == 2
    assert 'not-for-trace' not in str(row.output_snapshot)
    assert u.staff.engine_status(u.db)['effective_sales_engine'] == 'langgraph'


def test_replay_after_prompt_change_and_missing_credentials(unit, monkeypatch):
    u = unit
    first = run(u)
    u.publish(max_iterations=4, enabled_tools=['get_project_overview'])
    monkeypatch.delenv('OPENROUTER_API_KEY')
    second = run(u)
    assert second['replayed'] and second['run_id'] == first['run_id']
    assert second['message_id'] == first['message_id']
    assert second['published_version_id'] == u.version
    assert len(u.calls) == 1 and u.db.query(u.Message).count() == 2


def test_failed_sdk_retry_uses_original_version(unit):
    u = unit
    u.behavior.fail = True
    with pytest.raises(RuntimeError, match='Fake SDK failure'):
        run(u)
    row = u.db.query(u.Run).one()
    assert row.status == 'failed' and row.prompt_configuration_id == u.version
    assert u.db.query(u.Receipt).count() == 0
    assert u.db.query(u.Message).count() == 1
    u.publish(enabled_tools=['get_project_overview'])
    u.behavior.fail = False
    assert run(u)['run_id'] == row.id
    assert u.calls[0] == u.calls[1]
    assert u.db.query(u.Run).count() == 1


def test_receipt_failure_rolls_back_visible_output_and_run(unit):
    u = unit
    u.behavior.fail_commit = True
    with pytest.raises(RuntimeError, match='Fake receipt failure'):
        run(u)
    assert u.db.query(u.Run).one().status == 'failed'
    assert u.db.query(u.Receipt).count() == 0
    assert u.db.query(u.Message).filter_by(direction='outbound').count() == 0


def test_event_id_cannot_change_message(unit):
    run(unit)
    with pytest.raises(PermissionError, match='another message'):
        run(unit, message='Different message')
    assert len(unit.calls) == 1


def test_legacy_event_cannot_be_taken_over(unit):
    u = unit
    event = 'hermes:staged:legacy'
    u.db.add(u.Run(conversation_id=u.scope.conversation_id, event_id=event, graph_version='sales-langgraph/2.0', status='completed'))
    u.db.commit()
    with pytest.raises(u.selection.EngineSelectionError):
        run(u, event=event)
    assert not u.calls and u.db.query(u.Message).count() == 0


def test_old_legacy_pin_blocks_hermes(unit):
    u = unit
    c = u.db.get(u.Conversation, u.scope.conversation_id)
    event = 'simulation:legacy'
    pin = u.router.decide(scope=u.router.event_scope(c, event), status={'active_sales_engine': 'langgraph'})
    row = u.Message(conversation_id=c.id, channel='simulation', direction='inbound', role='user', status='received',
        provider_message_id=event, content='Hello', metadata_json={'lead_id':u.scope.lead_id, 'sales_engine_pin':pin})
    u.db.add(row); u.db.commit()
    with pytest.raises(u.selection.EngineSelectionError):
        u.staged.execute_isolated_turn(u.db, u.scope, inbound_message_id=row.id)
    assert not u.calls


@pytest.mark.parametrize('attribute,value', [('is_demo',False),('is_opt_out',True),('consent_status','unknown'),('agent_status','human_control'),('deleted_at',datetime.now(timezone.utc).replace(tzinfo=None))])
def test_unsafe_lead_rejected(unit, attribute, value):
    u = unit
    setattr(u.db.get(u.Lead, u.scope.lead_id), attribute, value);u.db.commit()
    with pytest.raises(PermissionError): run(u)
    assert not u.calls and u.db.query(u.Message).count()==0


@pytest.mark.parametrize('channel', ['sms','whatsapp'])
def test_real_channels_rejected(unit, channel):
    u=unit
    u.db.get(u.Conversation, u.scope.conversation_id).channel=channel;u.db.commit()
    with pytest.raises(PermissionError): run(u)
    assert not u.calls


def test_disabled_policy_does_not_create_event(unit):
    unit.publish(enabled=False)
    with pytest.raises(PermissionError): run(unit)
    assert not unit.calls and unit.db.query(unit.Message).count()==0


def test_invalid_receipt_not_replayed(unit):
    u=unit
    first=run(u)
    out=u.db.get(u.Message, first['message_id'])
    out.metadata_json={**out.metadata_json,'hermes_version_id':'wrong-version'};u.db.commit()
    with pytest.raises(PermissionError,match='Inconsistent'): run(u)
    assert len(u.calls)==1 and u.db.query(u.Message).count()==2


def test_normal_selector_still_blocks_hermes(unit):
    with pytest.raises(unit.selection.EngineUnavailable):
        unit.router.decide(scope=unit.router.event_scope(unit.db.get(unit.Conversation,unit.scope.conversation_id),'event'),status={'active_sales_engine':'hermes','published_version_id':unit.version})
    assert unit.selection.live_hermes_ready() is False


def test_existing_attributed_inbound_uses_same_event(unit):
    u=unit
    row=u.Message(conversation_id=u.scope.conversation_id,channel='simulation',direction='inbound',role='user',status='received',provider_message_id='simulation:explicit',content='What do you have?',metadata_json={'lead_id':u.scope.lead_id})
    u.db.add(row);u.db.commit()
    result=u.staged.execute_isolated_turn(u.db,u.scope,inbound_message_id=row.id)
    assert result['event_id']=='simulation:explicit'
    assert u.db.query(u.Run).one().event_id=='simulation:explicit'


def test_no_production_environment(unit, monkeypatch):
    monkeypatch.setenv('ENVIRONMENT','production')
    with pytest.raises(PermissionError,match='test or staging'): run(unit)
    assert not unit.calls


@pytest.mark.parametrize('database,allowed', [('blackpenguin',False),('blackpenguin_prod_test',False),('blackpenguin_test',True),('bp-staging',True),('latest',False)])
def test_database_name_guard(unit,database,allowed):
    from sqlalchemy.engine import make_url
    dummy=SimpleNamespace(get_bind=lambda:SimpleNamespace(url=make_url('postgresql://example.invalid/'+database)))
    if allowed: unit.staged.require_staging_database(dummy,environment='staging')
    else:
        with pytest.raises(PermissionError): unit.staged.require_staging_database(dummy,environment='staging')
