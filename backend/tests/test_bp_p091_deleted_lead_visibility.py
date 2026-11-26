"""P09.1 checks: deleted leads cannot appear or be opened in Agent.

The exact production functions are loaded from the new module without needing
application secrets or a live PostgreSQL / provider connection.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, HTTPException
from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.orm import Session, declarative_base

SOURCE = Path(__file__).resolve().parents[1] / 'app/modules/sales_agent/p091_visibility.py'
MAIN = Path(__file__).resolve().parents[1] / 'app/main.py'
Base = declarative_base()


class Lead(Base):
    __tablename__ = 'leads'
    id = Column(String, primary_key=True)
    company_id = Column(String)
    deleted_at = Column(DateTime)


class SalesConversation(Base):
    __tablename__ = 'sales_conversations'
    id = Column(String, primary_key=True)
    lead_id = Column(String)
    company_id = Column(String)


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Lead(id='a-active', company_id='C1'),
            Lead(id='a-deleted', company_id='C1', deleted_at=__import__('datetime').datetime(2026, 11, 25)),
            Lead(id='b-active', company_id='C2'),
            SalesConversation(id='thread-active', lead_id='a-active', company_id='C1'),
            SalesConversation(id='thread-deleted', lead_id='a-deleted', company_id='C1'),
            SalesConversation(id='thread-other-company', lead_id='b-active', company_id='C2'),
        ])
        session.commit()
        yield session
    engine.dispose()


def production_functions():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {'only_active_conversations', 'guard_active_conversation'}]
    namespace = {
        'db': None,
        'Lead': Lead, 'SalesConversation': SalesConversation,
        'Request': object, 'Session': Session,
        'Depends': Depends, 'get_db': lambda: None,
        'HTTPException': HTTPException,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


def test_inbox_hides_deleted_lead_without_hiding_another_project_or_tenant(db):
    only_active = production_functions()['only_active_conversations']
    summaries = [
        {'id': 'thread-active', 'lead_id': 'a-active'},
        {'id': 'thread-deleted', 'lead_id': 'a-deleted'},
        {'id': 'thread-other-company', 'lead_id': 'b-active'},
    ]
    assert [r['id'] for r in only_active(db, company_id='C1', summaries=summaries)] == ['thread-active']
    assert [r['id'] for r in only_active(db, company_id='C2', summaries=summaries)] == ['thread-other-company']


def test_deleted_conversation_cannot_be_reopened_by_direct_uuid(db):
    guard = production_functions()['guard_active_conversation']
    for conversation_id in ('thread-deleted', 'not-found'):
        with pytest.raises(HTTPException) as error:
            guard(SimpleNamespace(path_params={'conversation_id': conversation_id}), db)
        assert error.value.status_code == 404
    assert guard(SimpleNamespace(path_params={'conversation_id': 'thread-active'}), db) is None


def test_guard_does_not_interfere_with_non_conversation_routes(db):
    guard = production_functions()['guard_active_conversation']
    assert guard(SimpleNamespace(path_params={}), db) is None


def test_visibility_route_is_registered_first_and_guard_applies_to_agent_actions():
    body = MAIN.read_text(encoding='utf-8')
    assert body.index('app.include_router(p091_visibility_router') < body.index('app.include_router(sales_agent_router')
    assert 'dependencies=[Depends(guard_active_conversation)]' in body
    frontend = Path(__file__).resolve().parents[2] / 'frontend/src/app/app.routes.ts'
    # This backend source tree may be run standalone without the frontend.
    if frontend.exists():
        assert "import('./pages/client/agent/agent-p091')" in frontend.read_text(encoding='utf-8')
