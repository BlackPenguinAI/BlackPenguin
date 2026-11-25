"""SQLAlchemy-backed P04 executor tests: scoped receipts, idempotency, rollback.

The production booking/calendar implementation is NOT executed in these unit
cases; its integration with BP/PostgreSQL is a P7 staging acceptance test.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import importlib
import sys
import types

import pytest
from sqlalchemy import Column, DateTime, ForeignKey, String, JSON

# Reuse P03's minimal real-SQLAlchemy fixtures; never contact production DB.
from test_bp_hermes_p03_state import orm, db
from app.modules.hermes_sales_core.contracts import TurnScope

S = TurnScope('comp-a','proj-a','conv-a','lead-a')


@pytest.fixture
def executor_env(orm,db,monkeypatch):
    models=importlib.import_module('app.modules.hermes_sales_core.bp_operation_models')
    models.HermesSalesOperation.__table__.create(db.bind,checkfirst=True)
    executor=importlib.import_module('app.modules.hermes_sales_core.bp_effect_executor')
    lead=db.get(orm.Lead,'lead-a')
    lead.is_demo=True
    lead.is_opt_out=False
    lead.consent_status='granted_simulation'
    lead.agent_status='active'
    conversation=db.get(orm.SalesConversation,'conv-a')
    conversation.is_paused=False
    conversation.pause_reason=None
    return types.SimpleNamespace(executor=executor,operation_model=models.HermesSalesOperation,
                                 orm=orm,db=db,lead=lead,conversation=conversation)


def _pending_cancel(env,*,request_id='request-a'):
    inbound=env.db.get(env.orm.SalesMessage,'inbound-a')
    inbound.content='Please cancel my appointment'
    expiry=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    state=env.orm.store.blank_state(S)
    state['confirmation_request']={
        'id':request_id,'kind':'cancel','status':'execution_requested',
        'meeting_id':'m-1','booking_sha256':'fake-for-stub',
        'confirmed_inbound_message_id':'inbound-a','expires_at':expiry}
    result=env.orm.store.save(env.db,S,expected_revision=0,event_key='draft-a',
                              event_type='simulation_receipt',state=state)
    env.db.commit()
    return result


def test_live_conversation_is_never_executable(executor_env):
    env=executor_env
    env.conversation.channel='whatsapp'
    with pytest.raises(PermissionError,match='simulation conversation'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                       inbound_message_id='inbound-a',human_request=True)
    assert env.db.query(env.operation_model).count()==0


def test_non_demo_lead_is_never_executable(executor_env):
    env=executor_env
    env.lead.is_demo=False
    with pytest.raises(PermissionError,match='demo lead'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                       inbound_message_id='inbound-a',human_request=True)


def test_opt_out_lead_never_executes(executor_env):
    env=executor_env;env.lead.is_opt_out=True
    with pytest.raises(PermissionError,match='opted out'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                       inbound_message_id='inbound-a',human_request=True)


def test_no_consent_lead_never_executes(executor_env):
    env=executor_env;env.lead.consent_status='unknown'
    with pytest.raises(PermissionError,match='consent'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                       inbound_message_id='inbound-a',human_request=True)


def test_completed_request_returns_same_receipt_without_second_effect(executor_env,monkeypatch):
    env=executor_env;state=_pending_cancel(env)
    attempts=[]
    def fake_commit(*args):
        attempts.append(True)
        return {'status':'cancelled','meeting_id':'m-1','calendar_status':'simulation'}
    monkeypatch.setattr(env.executor,'_perform',fake_commit)
    first=env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=state.revision,
                                                         inbound_message_id='inbound-a')
    env.db.commit()
    assert first['status']=='cancelled' and first['replayed'] is False
    assert env.db.query(env.operation_model).count()==1
    assert env.orm.store.load(env.db,S).revision==state.revision+1
    second=env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=state.revision,
                                                          inbound_message_id='inbound-a')
    assert second['status']=='cancelled' and second['replayed'] is True
    assert attempts==[True]


def test_stale_revision_prevents_operation(executor_env,monkeypatch):
    env=executor_env;_pending_cancel(env)
    called=[]
    monkeypatch.setattr(env.executor,'_perform',lambda *a:(called.append(True),{})[1])
    with pytest.raises(env.orm.store.HermesStateConflict,match='stale'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                       inbound_message_id='inbound-a')
    assert called==[] and env.db.query(env.operation_model).count()==0


def test_failed_effect_does_not_write_hermes_receipt(executor_env,monkeypatch):
    env=executor_env;initial=_pending_cancel(env)
    def failed(*args):
        raise ValueError('No eligible advisor')
    monkeypatch.setattr(env.executor,'_perform',failed)
    with pytest.raises(ValueError,match='eligible advisor'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=initial.revision,
                                                       inbound_message_id='inbound-a')
    env.db.rollback()
    assert env.db.query(env.operation_model).count()==0
    assert env.orm.store.load(env.db,S).revision==initial.revision


def test_buyer_must_actually_request_cancel(executor_env,monkeypatch):
    env=executor_env;initial=_pending_cancel(env)
    env.db.get(env.orm.SalesMessage,'inbound-a').content='What time does it start?'
    monkeypatch.setattr(env.executor,'_perform',lambda *a:pytest.fail('No effect allowed'))
    with pytest.raises(PermissionError,match='Direct buyer cancellation'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=initial.revision,
                                                       inbound_message_id='inbound-a')


def test_no_foreign_scope_receipt(executor_env):
    env=executor_env
    foreign=TurnScope('comp-a','proj-b','conv-a','lead-a')
    with pytest.raises(PermissionError):
        env.executor.execute_p04_simulation_operation(env.db,foreign,expected_revision=0,
                                                       inbound_message_id='inbound-a',human_request=True)
    assert env.db.query(env.operation_model).count()==0


def test_receipt_rejects_changed_action_payload(executor_env,monkeypatch):
    env=executor_env;state=_pending_cancel(env)
    monkeypatch.setattr(env.executor,'_perform',lambda *a:{'status':'cancelled'})
    env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=state.revision,
                                                  inbound_message_id='inbound-a')
    env.db.commit()
    row=env.db.query(env.operation_model).one()
    row.request_hash='modified'  # Only tamper the local test transaction, not production.
    env.db.flush()
    with pytest.raises(env.orm.store.HermesStateConflict,match='different request'):
        env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=state.revision,
                                                       inbound_message_id='inbound-a')


def test_operation_model_is_registered_on_same_metadata(executor_env):
    env=executor_env
    assert env.operation_model.__table__.metadata is env.orm.Base.metadata
    assert env.operation_model.__table__.name=='hermes_sales_operations'


def test_human_request_creates_a_single_scoped_review_case(executor_env, monkeypatch):
    env=executor_env
    class HumanCase(env.orm.Base):
        __tablename__='human_intervention_cases'
        id=Column(String(36),primary_key=True,default='case-1')
        company_id=Column(String(36),ForeignKey('companies.id'))
        project_id=Column(String(36),ForeignKey('projects.id'))
        conversation_id=Column(String(36),ForeignKey('sales_conversations.id'))
        lead_id=Column(String(36),ForeignKey('leads.id'))
        reason=Column(String(60)); evidence=Column(String(2000)); confidence=Column(String(20))
        status=Column(String(20));dedupe_key=Column(String(160))
    HumanCase.__table__.create(env.db.bind,checkfirst=True)
    stub=types.ModuleType('app.modules.governance.models')
    stub.HumanInterventionCase=HumanCase
    monkeypatch.setitem(sys.modules,'app.modules.governance.models',stub)
    env.db.get(env.orm.SalesMessage,'inbound-a').content='I want to talk to a human'
    first=env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                         inbound_message_id='inbound-a',human_request=True)
    env.db.commit()
    assert first['status']=='human_review_requested'
    assert env.db.query(HumanCase).count()==1
    assert env.lead.agent_status=='human_control'
    assert env.conversation.is_paused is True
    second=env.executor.execute_p04_simulation_operation(env.db,S,expected_revision=0,
                                                          inbound_message_id='inbound-a',human_request=True)
    assert second['replayed'] is True
    assert env.db.query(HumanCase).count()==1
