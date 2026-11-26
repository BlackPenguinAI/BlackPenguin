"""Multi-company, multi-project opportunity discovery never crosses tenants."""
from __future__ import annotations
import ast
from datetime import datetime
from pathlib import Path
from sqlalchemy import Column, String, DateTime, ForeignKey, create_engine, func
from sqlalchemy.orm import Session, declarative_base

Base = declarative_base()
ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'app/modules/sales_agent/p09_opportunities.py'

class Project(Base):
    __tablename__ = 'projects'
    id = Column(String, primary_key=True)
    company_id = Column(String)
    name = Column(String)

class Lead(Base):
    __tablename__ = 'leads'
    id = Column(String, primary_key=True)
    company_id = Column(String)
    project_id = Column(String, ForeignKey('projects.id'))
    phone = Column(String)
    deleted_at = Column(DateTime)
    created_at = Column(DateTime)
    last_interaction_at = Column(DateTime)
    agent_status = Column(String)
    pipeline_stage = Column(String)

class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(String, primary_key=True)
    lead_id = Column(String, ForeignKey('leads.id'))
    project_id = Column(String, ForeignKey('projects.id'))


def _call(db, company_id, phone):
    tree = ast.parse(MODULE.read_text(encoding='utf-8'))
    function = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'company_opportunities')
    env = {'Lead': Lead, 'Project': Project, 'Meeting': Meeting, 'func': func, 'Session': Session}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(MODULE), 'exec'), env)
    return env['company_opportunities'](db, company_id=company_id, phone=phone)


def test_same_number_preserves_a_and_b_but_not_c2_or_deleted_leads():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Project(id='a', company_id='c1', name='Project A'),
                    Project(id='b', company_id='c1', name='Project B'),
                    Project(id='c', company_id='c2', name='Project C')])
        db.add_all([
            Lead(id='lead-a', company_id='c1', project_id='a', phone='+51 999-888-777',
                 created_at=datetime(2026,11,1), agent_status='active', pipeline_stage='exploring'),
            Lead(id='lead-b', company_id='c1', project_id='b', phone='+51999888777',
                 created_at=datetime(2026,11,2), agent_status='active', pipeline_stage='booking'),
            Lead(id='lead-deleted', company_id='c1', project_id='a', phone='+51999888777',
                 deleted_at=datetime(2026,11,3), created_at=datetime(2026,11,1)),
            Lead(id='lead-c', company_id='c2', project_id='c', phone='+51999888777',
                 created_at=datetime(2026,11,4), agent_status='active', pipeline_stage='new'),
        ])
        db.add(Meeting(id='visit-a', lead_id='lead-a', project_id='a'))
        db.commit()
        c1 = _call(db, 'c1', '+51 (999) 888 777')
        assert [row['lead_id'] for row in c1] == ['lead-b','lead-a']
        assert [row['appointment_count'] for row in c1] == [0, 1]
        assert all(row['company_id'] == 'c1' for row in c1)
        assert [row['lead_id'] for row in _call(db, 'c2', '+51999888777')] == ['lead-c']
        assert _call(db, 'c1', '+51999123456') == []
    engine.dispose()
