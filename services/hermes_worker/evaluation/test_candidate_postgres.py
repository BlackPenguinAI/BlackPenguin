"""HEI-06 certification lane: actual BlackPenguin ORM, isolated PostgreSQL 16.

Run only in the dedicated CI job, never a tenant or production database.
Provider and model remain doubles; the readiness override is test-local.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
import test_bp_hei03b3_worker_delivery as worker
import test_bp_hei03b4_live_changes as changes


pytestmark = pytest.mark.usefixtures('hei06_lane_engine')


@pytest.fixture
def hei06_lane_engine():
    raw = os.environ.get('HEI06_POSTGRES_URL', '')
    if not raw:
        pytest.fail('HEI06 PostgreSQL NOT_RUN: disposable URL missing')
    url = make_url(raw)
    if (os.environ.get('ENVIRONMENT') != 'test' or os.environ.get('DATABASE_URL') != 'sqlite://'
            or url.drivername != 'postgresql+psycopg2' or url.host != 'hei06-postgres'
            or url.port != 5432 or url.database != 'bp_hei06_test' or url.username != 'bp_hei06_test'
            or not url.password or url.query):
        pytest.fail('HEI06 requires the dedicated isolated PostgreSQL identity')
    root = create_engine(url, pool_pre_ping=True)
    schema = 'hei06_' + uuid4().hex
    engine = None
    created = False
    try:
        with root.begin() as conn:
            db, user, version = conn.execute(text('SELECT current_database(), current_user, current_setting(\'server_version_num\')')).one()
            assert (db, user) == ('bp_hei06_test', 'bp_hei06_test') and 160000 <= int(version) < 170000
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, pool_pre_ping=True)
        with engine.connect() as conn:
            assert conn.execute(text('SELECT current_schema()')).scalar_one() == schema
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with root.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def test_pg_native_worker_and_provider_receipt(real_lane):
    assert real_lane.db.get_bind().dialect.name == 'postgresql'
    worker.test_shared_dispatcher_completes_real_orm_turn(real_lane)


def test_pg_queued_receipt_is_reconciled_once(real_lane):
    worker.test_queued_receipt_polls_without_second_send_or_model(real_lane)


def test_pg_unknown_receipt_never_resends(real_lane):
    worker.test_existing_unknown_outbox_requires_review(real_lane)


def test_pg_consent_stop_never_invokes_sdk(real_lane):
    worker.test_stop_without_sdk_or_agent_run(real_lane)


def test_pg_handoff_never_invokes_sdk(real_lane):
    worker.test_handoff_without_sdk_or_agent_run(real_lane)


def test_pg_private_preparation_releases_transaction(real_lane, monkeypatch):
    worker.test_private_preparation_releases_database_before_sdk(real_lane, monkeypatch)


@pytest.mark.parametrize('initial', [False, True], ids=['first-write', 'existing-state'])
def test_pg_actual_state_writers_one_revision(real_lane, initial):
    from app.modules.hermes_sales_core.bp_models import HermesSalesStateEvent
    from app.modules.hermes_sales_core.bp_state_store import blank_state, load, save, HermesStateConflict
    lane = real_lane
    scope = lane.scope
    db = lane.db
    engine = db.get_bind()
    if initial:
        save(db, scope, expected_revision=0, event_key='initial', state=blank_state(scope))
        db.commit()
    expected = int(initial)
    barrier = Barrier(2)

    def write(marker):
        with Session(engine, autoflush=False) as session:
            current = load(session, scope)
            assert current.revision == expected
            session.commit()
            state = deepcopy(current.data)
            state['last_assistant_reply'] = marker
            barrier.wait(timeout=15)
            try:
                result = save(session, scope, expected_revision=expected, event_key='race-' + marker, state=state)
                session.commit()
                return ('committed', result.revision)
            except HermesStateConflict:
                session.rollback()
                return ('conflict', expected)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, x) for x in ('first', 'second')]
        result = [f.result(timeout=35) for f in futures]
    assert sorted(x[0] for x in result) == ['committed', 'conflict']
    db.expire_all()
    assert load(db, scope).revision == expected + 1
    assert db.query(HermesSalesStateEvent).filter_by(**scope.__dict__).count() == expected + 1


def test_pg_native_material_effect_and_retry(real_lane, tmp_path, monkeypatch):
    worker.test_real_material_issue_dispatch_and_receipt(real_lane, tmp_path, monkeypatch)


def test_pg_native_booking_effect_and_retry(real_lane):
    worker.test_real_booking_effect_and_confirmation(real_lane)


@pytest.mark.parametrize('kind', ['cancel', 'reschedule'])
def test_pg_native_visit_change_and_retry(real_lane, kind):
    changes.test_native_change_end_to_end_and_retry(real_lane, kind)


def test_pg_reschedule_failure_preserves_original(real_lane):
    changes.test_reschedule_unavailable_preserves_original(real_lane)


def test_pg_claimers_cannot_claim_same_job(real_lane, monkeypatch):
    from app.modules.sales_agent import live_worker
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timedelta
    db = real_lane.db
    engine = db.get_bind()
    job = db.get(real_lane.Job,'job')
    job.status='pending';job.scheduled_at=datetime.utcnow()-timedelta(seconds=1)
    db.commit()
    monkeypatch.setattr(live_worker,'SessionLocal',sessionmaker(bind=engine,autoflush=False))
    barrier=Barrier(2)
    def claim():
        barrier.wait(timeout=10)
        return live_worker._claim_inbound_jobs(limit=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(claim) for _ in range(2)]
        results=[f.result(timeout=20) for f in futures]
    assert sorted(results,key=len)==[[],['job']]
    db.expire_all()
    assert db.get(real_lane.Job,'job').status=='processing'
