"""HEI-01A hermetic selector/dispatcher tests.

Loads the actual HEI modules and existing P05 ORM model in an isolated package
namespace. The Sales rows are intentionally minimal SQLite fixtures, tool schemas
and identity checks are doubles; no SDK, providers, or production database.
Full repo/PG/provider acceptance is a separate release gate.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Boolean, Column, DateTime, JSON, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'modules'


@pytest.fixture
def unit(monkeypatch, tmp_path):
    base = declarative_base()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, autoflush=False)

    def module(name, **attributes):
        obj = types.ModuleType(name)
        obj.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, obj)
        return obj

    def package(name, path):
        return module(name, __path__=[str(path)])

    def load(package_obj, filename):
        name = package_obj.__name__ + '.' + filename
        path = Path(package_obj.__path__[0]) / (filename + '.py')
        spec = importlib.util.spec_from_file_location(name, path)
        obj = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, obj)
        setattr(package_obj, filename, obj)
        spec.loader.exec_module(obj)
        return obj

    class User(base):
        __tablename__ = 'users'
        id = Column(String(36), primary_key=True)

    class Lead(base):
        __tablename__ = 'leads'
        id = Column(String, primary_key=True)
        company_id = Column(String)
        project_id = Column(String)
        deleted_at = Column(DateTime)

    class SalesConversation(base):
        __tablename__ = 'sales_conversations'
        id = Column(String, primary_key=True)
        company_id = Column(String)
        project_id = Column(String)
        lead_id = Column(String)
        provider = Column(String)
        channel = Column(String)

    class SalesMessage(base):
        __tablename__ = 'sales_messages'
        id = Column(String, primary_key=True)
        conversation_id = Column(String)
        provider_message_id = Column(String)
        direction = Column(String)
        role = Column(String)
        metadata_json = Column(JSON, default=dict)
        created_at = Column(DateTime, default=datetime.utcnow)

    class SalesConversationLeadContext(base):
        __tablename__ = 'sales_conversation_lead_contexts'
        id = Column(String, primary_key=True)
        conversation_id = Column(String)
        lead_id = Column(String)
        is_active = Column(Boolean, default=True)
        activated_at = Column(DateTime)

    class AgentRun(base):
        __tablename__ = 'agent_runs'
        event_id = Column(String, primary_key=True)
        conversation_id = Column(String)
        graph_version = Column(String)
        prompt_configuration_id = Column(String)

    class SalesInboundJob(base):
        __tablename__ = 'sales_inbound_jobs'
        id = Column(String, primary_key=True)
        conversation_id = Column(String)
        message_id = Column(String)
        status = Column(String)
        processed_at = Column(DateTime)
        error_code = Column(String)
        error_message = Column(String)

    class SalesFollowUpJob(base):
        __tablename__ = 'sales_follow_up_jobs'
        id = Column(String, primary_key=True)
        conversation_id = Column(String)
        status = Column(String)
        kind = Column(String)
        payload_json = Column(JSON, default=dict)
        reason = Column(String)
        processed_at = Column(DateTime)

    def get_db():
        with factory() as db:
            yield db

    module('app.db.postgres', Base=base, SessionLocal=factory, get_db=get_db)
    module('app.modules.sales_crm.models', Lead=Lead)
    root = package('_hei01a_fixture', ROOT)
    hp = package(root.__name__ + '.hermes_sales_core', ROOT / 'hermes_sales_core')
    sp = package(root.__name__ + '.sales_agent', ROOT / 'sales_agent')
    selection = load(hp, 'engine_selection')
    monkeypatch.setitem(sys.modules, 'app.modules.hermes_sales_core.engine_selection', selection)
    config = load(hp, 'config')
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Verified commercial information only. ' * 5, encoding='utf-8')
    monkeypatch.setattr(config, 'PROMPT_PATH', prompt)
    schema = module(hp.__name__ + '.tool_schemas', SCHEMAS={
        'search_properties': {}, 'get_project_overview': {}})
    hp.tool_schemas = schema
    staff_models = load(hp, 'staff_models')
    control = load(hp, 'staff_config')
    monkeypatch.setitem(sys.modules, 'app.modules.hermes_sales_core.staff_config', control)
    sp.models = module(sp.__name__ + '.models', SalesConversation=SalesConversation,
                       SalesMessage=SalesMessage, SalesConversationLeadContext=SalesConversationLeadContext,
                       AgentRun=AgentRun, SalesInboundJob=SalesInboundJob, SalesFollowUpJob=SalesFollowUpJob)
    load(sp, 'conversation_scope')  # actual scope query, not a fixture implementation
    sp.concurrency = module(sp.__name__ + '.concurrency', bounded=lambda db: db)
    router = load(sp, 'engine_router')

    # The API is tested with a stand-in identity dependency. This verifies the
    # role contract on the actual route, not production auth/token validation.
    class RoleChecker:
        def __init__(self, roles):
            self.roles = roles
        def __call__(self, x_test_role: str = Header(default='')):
            if x_test_role not in self.roles:
                raise HTTPException(403, 'Forbidden')
            return SimpleNamespace(id='staff-a')
    module('app.modules.auth.deps', RoleChecker=RoleChecker)
    module('app.modules.users.models', User=User, UserRole=SimpleNamespace(SUPERADMIN='superadmin'))
    api = load(hp, 'engine_staff_router')

    base.metadata.create_all(engine)
    with factory() as db:
        db.add(User(id='staff-a'))
        db.commit()
    try:
        yield SimpleNamespace(factory=factory, selection=selection, control=control,
                              models=staff_models, router=router, api=api,
                              Lead=Lead, Conversation=SalesConversation,
                              Message=SalesMessage, Context=SalesConversationLeadContext,
                              Run=AgentRun, Inbound=SalesInboundJob, FollowUp=SalesFollowUpJob)
    finally:
        engine.dispose()


def publish(unit, db, *, enabled=False, iterations=12):
    policy = unit.control.baseline()
    policy.update(enabled=enabled, max_iterations=iterations)
    version = unit.control.create_draft(db, configuration=policy, note='test policy', actor_id='staff-a')
    unit.control.publish(db, version_id=version['id'], actor_id='staff-a')
    return version['id']


def set_stored(unit, db, engine):
    """Simulate old/corrupt/future persisted routing; never use to activate live."""
    row = db.get(unit.models.HermesGlobalSettings, 'global')
    if row is None:
        publish(unit, db)
        row = db.get(unit.models.HermesGlobalSettings, 'global')
    row.configuration = {**row.configuration, 'active_sales_engine': engine}
    db.commit()


def test_missing_registry_keeps_legacy(unit):
    with unit.factory() as db:
        status = unit.control.engine_status(db)
        assert status['active_sales_engine'] == status['effective_sales_engine'] == 'langgraph'
        assert status['target_default_engine'] == 'hermes'
        assert not status['hermes_live_ready'] and not status['automatic_fallback']
        assert db.get(unit.models.HermesGlobalSettings, 'global') is None


def test_p05_enabled_is_not_engine_selector(unit):
    with unit.factory() as db:
        publish(unit, db, enabled=True)
        snap = unit.control.snapshot(db)
        assert snap['configuration']['enabled'] is True
        assert 'active_sales_engine' not in snap['configuration']
        assert snap['engine_selection']['active_sales_engine'] == 'langgraph'
        assert snap['runtime_connected_to_live'] is False


def test_hermes_switch_refused_before_any_write(unit):
    with unit.factory() as db:
        with pytest.raises(unit.selection.EngineUnavailable):
            unit.control.select_sales_engine(db, engine='hermes', note='premature', actor_id='staff-a')
        assert db.get(unit.models.HermesGlobalSettings, 'global') is None
        assert unit.control.versions(db)['total'] == 0


def test_legacy_noop_no_new_version(unit):
    with unit.factory() as db:
        first = publish(unit, db)
        result = unit.control.select_sales_engine(db, engine='langgraph', note='keep legacy', actor_id='staff-a')
        assert result['published_version_id'] == first
        assert unit.control.versions(db)['total'] == 1


def test_selector_not_editable_through_prompt_draft(unit):
    with unit.factory() as db:
        policy = {**unit.control.baseline(), 'active_sales_engine': 'hermes'}
        with pytest.raises(ValidationError):
            unit.control.create_draft(db, configuration=policy, note='bypass', actor_id='staff-a')
        assert unit.control.versions(db)['total'] == 0


def test_prompt_publish_and_restore_never_switch_engine(unit):
    with unit.factory() as db:
        old = publish(unit, db, enabled=True)
        set_stored(unit, db, 'hermes')
        newer = publish(unit, db, enabled=True, iterations=4)
        assert unit.control.engine_status(db)['active_sales_engine'] == 'hermes'
        assert unit.control.engine_status(db)['effective_sales_engine'] is None
        restored = unit.control.restore(db, version_id=old, actor_id='staff-a')
        assert restored['configuration']['max_iterations'] == 12
        assert restored['published_version_id'] not in {old, newer}
        assert restored['engine_selection']['active_sales_engine'] == 'hermes'


def test_explicit_return_to_legacy_is_audited(unit):
    with unit.factory() as db:
        old = publish(unit, db, enabled=True)
        set_stored(unit, db, 'hermes')
        result = unit.control.select_sales_engine(db, engine='langgraph', note='controlled return', actor_id='staff-a')
        assert result['active_sales_engine'] == 'langgraph'
        assert result['published_version_id'] != old
        version = unit.control.find_version(db, result['published_version_id'])
        assert version.created_by_user_id == 'staff-a' and 'hermes -> langgraph' in version.change_note
        detail = unit.control.serialize_version(version, include_config=True)
        assert detail['active_sales_engine_at_change'] == 'langgraph'
        assert 'active_sales_engine' not in detail['configuration']
        assert detail['configuration']['enabled'] is True
        assert unit.control.versions(db)['total'] == 2


def test_invalid_selection_requires_explicit_repair(unit):
    with unit.factory() as db:
        publish(unit, db)
        set_stored(unit, db, 'unknown')
        status = unit.control.engine_status(db)
        assert status['effective_sales_engine'] is None
        assert status['error_code'] == 'INVALID_ENGINE_SELECTION'
        result = unit.control.select_sales_engine(db, engine='langgraph', note='repair', actor_id='staff-a')
        assert result['active_sales_engine'] == 'langgraph'


def test_explicit_select_is_versioned_when_future_gate_is_certified_in_double(unit, monkeypatch):
    # Only the test replaces readiness. The shipped release contains no bypass.
    monkeypatch.setattr(unit.selection, 'live_hermes_ready', lambda: True)
    with unit.factory() as db:
        old = publish(unit, db, enabled=True)
        new = unit.control.select_sales_engine(db, engine='hermes', note='test gate', actor_id='staff-a')
        assert new['active_sales_engine'] == 'hermes' and new['published_version_id'] != old
        # Publishing/restoring a configuration, even a historical switch version,
        # must not silently change the active route.
        switched = unit.control.select_sales_engine(db, engine='langgraph', note='return', actor_id='staff-a')
        assert switched['active_sales_engine'] == 'langgraph'
        restored = unit.control.restore(db, version_id=new['published_version_id'], actor_id='staff-a')
        assert restored['engine_selection']['active_sales_engine'] == 'langgraph'


def test_future_readiness_double_still_requires_enabled_policy(unit, monkeypatch):
    monkeypatch.setattr(unit.selection, 'live_hermes_ready', lambda: True)
    with unit.factory() as db:
        publish(unit, db, enabled=False)
        with pytest.raises(unit.selection.EngineUnavailable):
            unit.control.select_sales_engine(db, engine='hermes', note='disabled policy', actor_id='staff-a')
        db.rollback()
        assert unit.control.engine_status(db)['active_sales_engine'] == 'langgraph'


def test_api_staff_only_contract_and_409_gate(unit):
    app = FastAPI()
    app.include_router(unit.api.router, prefix='/ai')
    with TestClient(app) as client:
        path = '/ai/hermes/engine'
        assert client.get(path).status_code == 403
        assert client.put(path, json={'active_sales_engine':'langgraph','change_note':'x'}, headers={'x-test-role':'admin'}).status_code == 403
        headers = {'x-test-role':'superadmin'}
        r = client.get(path, headers=headers)
        assert r.status_code == 200 and r.json()['active_sales_engine'] == 'langgraph'
        assert r.headers['cache-control'] == 'no-store'
        r = client.put(path, headers=headers, json={'active_sales_engine':'hermes','change_note':'attempt'})
        assert r.status_code == 409 and r.json()['detail']['code'] == 'HERMES_NOT_READY'
        assert client.put(path, headers=headers, json={'active_sales_engine':'other','change_note':'x'}).status_code == 422
        assert client.put(path, headers=headers, json={'active_sales_engine':'langgraph','change_note':'x','company_id':'c'}).status_code == 422
        assert client.put(path, headers=headers, json={'active_sales_engine':'langgraph','change_note':'x'}).status_code == 200


def scope():
    return dict(event_id='e1', conversation_id='c1', company_id='co1', project_id='p1', lead_id='l1')


def test_decision_new_legacy_and_pin_survives_global_switch(unit):
    p = unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'})
    assert p['engine'] == 'langgraph'
    assert unit.router.decide(scope=scope(), status={'active_sales_engine':'hermes'}, pin=p) == p


def test_new_hermes_and_pinned_hermes_never_fall_back(unit):
    with pytest.raises(unit.selection.EngineUnavailable):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'hermes'})
    with pytest.raises(unit.selection.EngineUnavailable):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'}, pin={**scope(),'engine':'hermes'})


def test_existing_run_owns_engine(unit):
    legacy = SimpleNamespace(event_id='e1',conversation_id='c1',graph_version='sales-langgraph/2.0',prompt_configuration_id='old')
    p = unit.router.decide(scope=scope(), status={'active_sales_engine':'hermes'}, run=legacy)
    assert p['engine'] == 'langgraph' and p['policy_version_id'] == 'old'
    hermes = SimpleNamespace(event_id='e1',conversation_id='c1',graph_version='hermes-native/1.0',prompt_configuration_id='h1')
    with pytest.raises(unit.selection.EngineUnavailable):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'}, run=hermes)


@pytest.mark.parametrize('pin', [{**scope(),'engine':'other'}, {**scope(),'engine':'langgraph','lead_id':'foreign'}, {'engine':'langgraph'}])
def test_invalid_or_foreign_pin(unit, pin):
    with pytest.raises(unit.selection.EngineSelectionError):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'}, pin=pin)


def test_run_conflict_and_foreign_run(unit):
    run = SimpleNamespace(event_id='e1',conversation_id='c1',graph_version='hermes-native/1.0')
    with pytest.raises(unit.selection.EngineSelectionError):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'}, pin={**scope(),'engine':'langgraph'}, run=run)
    run.conversation_id = 'foreign'
    with pytest.raises(unit.selection.EngineSelectionError):
        unit.router.decide(scope=scope(), status={'active_sales_engine':'langgraph'}, run=run)


def seed_job(unit, *, inbound=True, kind='cadence', deleted=False, foreign=False, expired=False, state='processing'):
    with unit.factory() as db:
        db.add(unit.Lead(id='l1',company_id='co1',project_id='p1',deleted_at=datetime.utcnow() if deleted else None))
        db.add(unit.Conversation(id='c1',company_id='co1',project_id='p1',lead_id='l1',provider='telnyx',channel='sms'))
        if inbound:
            db.add(unit.Message(id='m1',conversation_id='c1',provider_message_id='prov1',direction='inbound',role='user',
                                metadata_json={'lead_id':'foreign' if foreign else 'l1','project_id':'p1','existing':'keep'}))
            if expired:
                db.add(unit.Context(id='ctx1',conversation_id='c1',lead_id='l1',activated_at=datetime.utcnow()+timedelta(days=1)))
            db.add(unit.Inbound(id='j1',conversation_id='c1',message_id='m1',status=state))
        else:
            db.add(unit.FollowUp(id='j1',conversation_id='c1',status=state,kind=kind,reason='existing reason',
                                 payload_json={'lead_id':'foreign' if foreign else 'l1','project_id':'p1','epoch':7}))
        db.commit()


def test_inbound_routes_once_and_pins_before_handler(unit):
    seed_job(unit)
    calls=[]
    async def legacy(job_id):
        with unit.factory() as db:
            msg=db.get(unit.Message,'m1')
            pin=msg.metadata_json[unit.router.PIN_KEY]
            assert pin['engine']=='langgraph' and pin['event_id']=='telnyx:prov1' and pin['lead_id']=='l1'
            assert msg.metadata_json['existing']=='keep'
            db.get(unit.Inbound,job_id).status='processed';db.commit()
        calls.append(job_id)
    assert asyncio.run(unit.router.route_live_job('j1',inbound=True,legacy_handler=legacy)) is True
    assert asyncio.run(unit.router.route_live_job('j1',inbound=True,legacy_handler=legacy)) is False
    assert calls==['j1']


def test_inbound_retry_keeps_original_engine_even_if_global_changed(unit):
    seed_job(unit)
    async def fail(_):
        raise RuntimeError('temporary failure')
    with pytest.raises(RuntimeError):
        asyncio.run(unit.router.route_live_job('j1',inbound=True,legacy_handler=fail))
    with unit.factory() as db:
        assert db.get(unit.Message,'m1').metadata_json[unit.router.PIN_KEY]['engine']=='langgraph'
        set_stored(unit,db,'hermes')
    calls=[]
    async def legacy(job_id):
        calls.append(job_id)
    assert asyncio.run(unit.router.route_live_job('j1',inbound=True,legacy_handler=legacy)) is True
    assert calls==['j1']


@pytest.mark.parametrize('kind,event_id',[('cadence','followup:j1'),('resume','resume:j1'),('inactivity','inactivity:j1')])
def test_scheduled_jobs_preserve_payload_and_select(unit,kind,event_id):
    seed_job(unit,inbound=False,kind=kind)
    calls=[]
    async def legacy(job_id):
        with unit.factory() as db:
            job=db.get(unit.FollowUp,job_id)
            assert job.payload_json['epoch']==7
            assert job.payload_json[unit.router.PIN_KEY]['event_id']==event_id
            assert job.payload_json[unit.router.PIN_KEY]['engine']=='langgraph'
        calls.append(job_id)
    assert asyncio.run(unit.router.route_live_job('j1',inbound=False,legacy_handler=legacy)) is True
    assert calls==['j1']


@pytest.mark.parametrize('inbound',[True,False])
def test_unready_hermes_no_legacy_and_job_review(unit,inbound):
    seed_job(unit,inbound=inbound)
    with unit.factory() as db:
        set_stored(unit,db,'hermes')
    async def must_not_run(_):
        pytest.fail('Unexpected legacy fallback')
    assert asyncio.run(unit.router.route_live_job('j1',inbound=inbound,legacy_handler=must_not_run)) is False
    with unit.factory() as db:
        job=db.get(unit.Inbound if inbound else unit.FollowUp,'j1')
        assert job.status=='review'
        if inbound:
            assert job.error_code=='HERMES_NOT_READY'
            assert db.get(unit.Message,'m1').metadata_json['agent_turn_status']=='review'
        else:
            assert job.payload_json['engine_routing_error']=='HERMES_NOT_READY'


@pytest.mark.parametrize('kwargs',[{'deleted':True},{'foreign':True},{'expired':True},{'inbound':False,'foreign':True}])
def test_deleted_stale_or_cross_opportunity_job_not_dispatched(unit,kwargs):
    seed_job(unit,**kwargs)
    async def must_not_run(_):
        pytest.fail('Out-of-scope job was dispatched')
    inbound=kwargs.get('inbound',True)
    assert asyncio.run(unit.router.route_live_job('j1',inbound=inbound,legacy_handler=must_not_run)) is False
    with unit.factory() as db:
        assert db.get(unit.Inbound if inbound else unit.FollowUp,'j1').status=='cancelled'


def test_future_gate_alone_cannot_dispatch_without_hermes_handler(unit, monkeypatch):
    seed_job(unit)
    with unit.factory() as db:
        set_stored(unit, db, 'hermes')
    monkeypatch.setattr(unit.selection, 'live_hermes_ready', lambda: True)
    async def must_not_run(_):
        pytest.fail('Legacy fallback is forbidden even if a future gate is true')
    assert asyncio.run(unit.router.route_live_job('j1', inbound=True, legacy_handler=must_not_run)) is False
    with unit.factory() as db:
        assert db.get(unit.Inbound, 'j1').status == 'review'
