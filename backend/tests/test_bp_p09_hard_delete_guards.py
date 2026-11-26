"""SQLite-backed guard tests for P09 deletion preflight.

No provider, filesystem or production DB is touched. The exact P09 function
bodies are loaded independently to avoid requiring real application settings.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import Column, String, create_engine, or_
from sqlalchemy.orm import Session, declarative_base

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'app/modules/sales_crm/p09_delete.py'
Base = declarative_base()


class Lead(Base):
    __tablename__ = 'leads'
    id = Column(String, primary_key=True)
    company_id = Column(String)
    project_id = Column(String)


class SalesConversation(Base):
    __tablename__ = 'sales_conversations'
    id = Column(String, primary_key=True)
    lead_id = Column(String)
    company_id = Column(String)


class SalesConversationLeadContext(Base):
    __tablename__ = 'sales_conversation_lead_contexts'
    id = Column(String, primary_key=True)
    lead_id = Column(String)
    conversation_id = Column(String)


class SalesInboundJob(Base):
    __tablename__ = 'sales_inbound_jobs'
    id = Column(String, primary_key=True)
    conversation_id = Column(String)
    status = Column(String)


class SalesFollowUpJob(Base):
    __tablename__ = 'sales_follow_up_jobs'
    id = Column(String, primary_key=True)
    conversation_id = Column(String)
    status = Column(String)


class OutboundMessage(Base):
    __tablename__ = 'outbound_messages'
    id = Column(String, primary_key=True)
    conversation_id = Column(String)
    status = Column(String)


class AgentRun(Base):
    __tablename__ = 'agent_runs'
    id = Column(String, primary_key=True)
    conversation_id = Column(String)
    status = Column(String)


class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(String, primary_key=True)
    lead_id = Column(String)
    gcal_event_id = Column(String)


class SalesMessage(Base):
    __tablename__ = 'sales_messages'
    id = Column(String, primary_key=True)
    conversation_id = Column(String)


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Lead(id='lead-a', company_id='c1', project_id='a'),
                         Lead(id='lead-b', company_id='c1', project_id='b'),
                         Lead(id='lead-c', company_id='c2', project_id='c')])
        session.commit()
        yield session
    engine.dispose()


def _preflight():
    nodes = ast.parse(MODULE.read_text(encoding='utf-8')).body
    functions = [item for item in nodes if isinstance(item, ast.FunctionDef)
                 and item.name in {'_conversations_for', '_preflight'}]
    env = {'SalesConversation': SalesConversation,
           'SalesConversationLeadContext': SalesConversationLeadContext,
           'SalesInboundJob': SalesInboundJob, 'SalesFollowUpJob': SalesFollowUpJob,
           'OutboundMessage': OutboundMessage, 'AgentRun': AgentRun,
           'Meeting': Meeting, 'or_': or_}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(MODULE), 'exec'), env)
    return env['_preflight']


def test_isolated_lead_has_no_blockers(db):
    db.add(SalesConversation(id='conv-a', company_id='c1', lead_id='lead-a'))
    db.commit()
    conversations, meetings, blockers = _preflight()(db, db.get(Lead, 'lead-a'))
    assert [c.id for c in conversations] == ['conv-a']
    assert meetings == [] and blockers == []


def test_shared_physical_route_blocks_both_opportunity_deletions(db):
    db.add(SalesConversation(id='shared', company_id='c1', lead_id='lead-b'))
    db.add_all([
        SalesConversationLeadContext(id='a-episode', lead_id='lead-a', conversation_id='shared'),
        SalesConversationLeadContext(id='b-episode', lead_id='lead-b', conversation_id='shared'),
    ])
    db.commit()
    for lead_id in ['lead-a', 'lead-b']:
        assert 'SHARED_OR_HISTORICAL_PROVIDER_THREAD' in _preflight()(db, db.get(Lead, lead_id))[2]
    assert _preflight()(db, db.get(Lead, 'lead-c'))[2] == []


def test_google_calendar_and_inflight_work_block_physical_delete(db):
    db.add(SalesConversation(id='conv-a', company_id='c1', lead_id='lead-a'))
    db.add(Meeting(id='meeting-a', lead_id='lead-a', gcal_event_id='google-123'))
    db.add(SalesInboundJob(id='active-a', conversation_id='conv-a', status='processing'))
    db.commit()
    blockers = _preflight()(db, db.get(Lead, 'lead-a'))[2]
    assert blockers == ['EXTERNAL_CALENDAR_RECONCILIATION_REQUIRED', 'IN_FLIGHT_OPERATION']


def test_deletion_lane_disabled_by_default(monkeypatch):
    env = {'os': __import__('os')}
    class FakeHttpException(Exception):
        def __init__(self, status_code, detail):
            self.status_code, self.detail = status_code, detail
    env['HTTPException'] = FakeHttpException
    module = ast.parse(MODULE.read_text(encoding='utf-8'))
    fn = next(x for x in module.body if isinstance(x, ast.FunctionDef) and x.name == '_enabled')
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MODULE), 'exec'), env)
    monkeypatch.delenv('BP_P09_HARD_DELETE_ENABLED', raising=False)
    with pytest.raises(FakeHttpException) as error:
        env['_enabled']()
    assert error.value.status_code == 409
