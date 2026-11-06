"""Opt-in real parallel writers; NEVER point at a production database.

Needs DIALOGUE_POSTGRES_TEST_URL with a database name ending in _test.
Each case creates and removes only its own random test schema.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Barrier
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
from app.modules.sales_agent.dialogue_store import Scope, DialogueConflict, save, load
from app.modules.sales_agent.understanding_contract import DialogueState


@pytest.mark.parametrize('initial_revision', [0, 1], ids=['first-writers','existing-state'])
def test_postgres_parallel_writers_preserve_single_revision_and_all_winning_evidence(initial_revision):
    url = os.environ.get('DIALOGUE_POSTGRES_TEST_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL URL not supplied; SQLite is not a parallel-worker proof.')
    engine = create_engine(url, pool_pre_ping=True)
    assert engine.dialect.name == 'postgresql'
    with engine.connect() as connection:
        database_name = connection.execute(text('SELECT current_database()')).scalar_one()
        assert database_name.endswith('_test'), 'Refusing non-test PostgreSQL database.'
    schema = 'bp_dialogue_test_' + uuid.uuid4().hex
    assert re.fullmatch(r'bp_dialogue_test_[0-9a-f]{32}', schema)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
    isolated = create_engine(url, connect_args={'options': f'-csearch_path={schema} -cstatement_timeout=15000'})
    try:
        Base.metadata.create_all(isolated)
        with Session(isolated) as db:
            company = Company(name='Disposable parallel fixture'); db.add(company); db.flush()
            project = Project(company_id=company.id, name='Generic fixture'); db.add(project); db.flush()
            lead = Lead(company_id=company.id, project_id=project.id, full_name='Fictional test lead',
                        phone='+15550100001', source='manual', platform='manual')
            db.add(lead); db.flush()
            conversation = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id,
                                             channel='sms', provider='telnyx', is_paused=False)
            db.add(conversation); db.flush()
            scope = Scope(company.id, project.id, conversation.id, lead.id); db.commit()
            if initial_revision:
                save(db, scope, event_key='initial', expected_revision=0, state=DialogueState()); db.commit()
        barrier = Barrier(2)
        def writer(key):
            with Session(isolated) as db:
                assert load(db, scope)[0] == initial_revision
                barrier.wait(timeout=10)
                try:
                    save(db, scope, event_key=key, expected_revision=initial_revision, state=DialogueState())
                    db.commit()
                    return key, 'saved'
                except DialogueConflict:
                    db.rollback()
                    return key, 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, ('writer-a','writer-b')))
        assert sorted(status for _, status in results) == ['conflict','saved']
        winner = next(key for key, status in results if status == 'saved')
        with Session(isolated) as db:
            assert load(db, scope)[0] == initial_revision + 1
            assert db.query(SalesDialogueEvent).count() == initial_revision + 1
            assert save(db, scope, event_key=winner, expected_revision=initial_revision, state=DialogueState())[0] == initial_revision + 1
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()
