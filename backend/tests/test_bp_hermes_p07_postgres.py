"""P07 real-PostgreSQL acceptance for the Hermes durable state and migrations.

Run ONLY against the disposable PostgreSQL container provided by
backend/tools/sales_ai/postgres_checks.py. Never point this at production.
When the isolated URL is absent, tests are explicitly skipped (NOT passed).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import runpy
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Reuse the existing true-SQLAlchemy P03 contract ORM; no production database
# or runtime module is imported through app.db.postgres in this fixture.
from test_bp_hermes_p03_state import orm, SCOPE, OTHER


@pytest.fixture
def sandbox_pg(orm):
    url = os.environ.get('DIALOGUE_POSTGRES_TEST_URL', '')
    if not url:
        pytest.skip('P07 real PostgreSQL isolation was NOT_RUN: missing DIALOGUE_POSTGRES_TEST_URL')
    if not url.startswith(('postgresql+psycopg2://', 'postgresql://')):
        pytest.fail('P07 requires a PostgreSQL URL, never SQLite or a live channel')
    # The preflight harness creates a disposable database and internal network.
    # A unique schema prevents collisions with the legacy PostgreSQL test suite.
    schema = 'hermes_p07_' + uuid4().hex[:12]
    root = create_engine(url, pool_pre_ping=True)
    with root.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_pre_ping=True,
                           connect_args={'options': f'-csearch_path={schema}'})
    Session = sessionmaker(bind=engine, autoflush=False)
    try:
        orm.Base.metadata.create_all(engine)
        with Session() as db:
            db.add_all([orm.Company(id='comp-a', is_active=True),
                        orm.Company(id='comp-b', is_active=True)])
            db.flush()
            db.add_all([orm.Project(id='proj-a', company_id='comp-a', is_active=True),
                        orm.Project(id='proj-b', company_id='comp-b', is_active=True)])
            db.flush()
            db.add(orm.Lead(id='lead-a', company_id='comp-a', project_id='proj-a'))
            db.flush()
            db.add(orm.SalesConversation(id='conv-a', company_id='comp-a',
                                         project_id='proj-a', lead_id='lead-a'))
            db.flush()
            db.add(orm.SalesConversationLeadContext(id='ctx-a', conversation_id='conv-a',
                                                     lead_id='lead-a', is_active=True))
            db.commit()
        yield (engine, Session, orm)
    finally:
        engine.dispose()
        with root.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def test_real_postgres_scoped_revisions_and_event_replay(sandbox_pg):
    engine, Session, orm = sandbox_pg
    with Session() as db:
        state = orm.store.blank_state(SCOPE)
        first = orm.store.save(db, SCOPE, expected_revision=0,
                               event_key='one', state=state)
        db.commit()
        assert first.revision == 1
        replay = orm.store.save(db, SCOPE, expected_revision=0,
                                event_key='one', state=state)
        assert replay.revision == 1
        assert db.query(orm.models.HermesSalesStateEvent).count() == 1
        with pytest.raises(PermissionError):
            orm.store.load(db, OTHER)
        db.rollback()
        assert orm.store.load(db, SCOPE).revision == 1
    assert 'hermes_sales_states' in inspect(engine).get_table_names()


def test_real_postgres_concurrent_writers_one_wins_one_conflicts(sandbox_pg):
    _, Session, orm = sandbox_pg
    with Session() as db:
        initial = orm.store.blank_state(SCOPE)
        orm.store.save(db, SCOPE, expected_revision=0,
                       event_key='initial', state=initial)
        db.commit()
    barrier = Barrier(2)

    def write_once(marker):
        with Session() as db:
            loaded = orm.store.load(db, SCOPE)
            assert loaded.revision == 1
            db.commit()  # never keep a read transaction open at the barrier
            proposed = deepcopy(loaded.data)
            proposed['last_assistant_reply'] = marker
            barrier.wait(timeout=12)
            try:
                saved = orm.store.save(db, SCOPE, expected_revision=1,
                                       event_key='writer-' + marker, state=proposed)
                db.commit()
                return ('committed', saved.revision)
            except orm.store.HermesStateConflict:
                db.rollback()
                return ('conflict', 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(write_once, 'a')
        second = pool.submit(write_once, 'b')
        results = [first.result(timeout=25), second.result(timeout=25)]
    assert sorted(status for status, _ in results) == ['committed', 'conflict']
    with Session() as db:
        assert orm.store.load(db, SCOPE).revision == 2
        assert db.query(orm.models.HermesSalesStateEvent).count() == 2


def test_real_postgres_p04_p05_additive_migration_round_trip(sandbox_pg):
    engine, _Session, _orm = sandbox_pg
    base = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with engine.begin() as conn:
        # This stub is needed only because the minimal P03 ORM omits staff users.
        conn.execute(text('CREATE TABLE users (id varchar(36) PRIMARY KEY)'))
        operations = Operations(MigrationContext.configure(conn))
        versions = []
        for name in ('20261125_hermes_sales_p04.py', '20261125_hermes_sales_p05.py'):
            ns = runpy.run_path(str(base / name))
            ns['upgrade'].__globals__['op'] = operations
            ns['downgrade'].__globals__['op'] = operations
            ns['upgrade']()
            versions.append(ns)
        columns = {item['name'] for item in inspect(conn).get_columns('hermes_global_versions')}
        assert {'id', 'version', 'configuration', 'is_published'} <= columns
        assert {'hermes_sales_operations', 'hermes_global_settings', 'hermes_global_versions'} <= set(inspect(conn).get_table_names())
        for ns in reversed(versions):
            ns['downgrade']()
        assert 'hermes_global_settings' not in inspect(conn).get_table_names()
        assert 'hermes_sales_operations' not in inspect(conn).get_table_names()
