"""Real database waits through the production webhook and worker boundary."""
import asyncio
from threading import Event
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from test_sales_runtime_postgres import postgres_case
from app.db.postgres import get_db
from app.modules.sales_agent import provider_router, live_worker
from app.modules.sales_agent.concurrency import bounded
from app.modules.sales_agent.models import ExternalWebhookEvent, SalesConversation, SalesInboundJob, SalesMessage


def application(engine, conversation_id, monkeypatch):
    app = FastAPI()
    app.include_router(provider_router.twilio_router)
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(provider_router, '_validate_twilio', lambda *args: SimpleNamespace(from_phone_number='+15550100002'))
    monkeypatch.setattr(provider_router, 'resolve_inbound_conversation', lambda db, **kwargs: db.get(SalesConversation, conversation_id))
    @app.get('/probe')
    async def probe():
        return {'alive': True}
    with Session(engine) as db:
        db.get(SalesConversation, conversation_id).is_paused = False
        db.commit()
    return app


def test_postgres_limits_are_local_and_reapplied(postgres_case):
    engine, _ = postgres_case
    with Session(engine) as db:
        original = db.execute(text('SHOW lock_timeout')).scalar_one()
        bounded(db)
        for _ in range(2):
            assert db.execute(text('SHOW lock_timeout')).scalar_one() == '2s'
            assert db.execute(text('SHOW idle_in_transaction_session_timeout')).scalar_one() == '2min'
            db.commit()
    with Session(engine) as db:
        assert db.execute(text('SHOW lock_timeout')).scalar_one() == original


def test_postgres_webhook_timeout_rolls_back_and_replay_queues_once(postgres_case, monkeypatch):
    engine, (_, conversation_id, _) = postgres_case
    app = application(engine, conversation_id, monkeypatch)
    payload = {'MessageSid': 'bounded-replay', 'To': '+15550100002', 'From': '+15550100001', 'Body': 'Three bedrooms please'}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            with Session(engine) as blocker:
                blocker.query(SalesConversation).filter_by(id=conversation_id).with_for_update().one()
                request = asyncio.create_task(client.post('/sms', data=payload))
                try:
                    await asyncio.sleep(.1)
                    assert (await asyncio.wait_for(client.get('/probe'), timeout=1)).status_code == 200
                    response = await asyncio.wait_for(request, timeout=5)
                    assert response.status_code == 503
                    assert response.headers['retry-after'] == '2'
                finally:
                    blocker.rollback()
                    await request
            with Session(engine) as db:
                assert db.query(ExternalWebhookEvent).count() == 0
                assert db.query(SalesInboundJob).count() == 0
                assert db.query(SalesMessage).filter_by(provider_message_id='bounded-replay').count() == 0
            assert (await client.post('/sms', data=payload)).status_code == 200
            assert (await client.post('/sms', data=payload)).status_code == 200
    asyncio.run(scenario())
    with Session(engine) as db:
        assert db.query(ExternalWebhookEvent).count() == 1
        assert db.query(SalesInboundJob).count() == 1
        assert db.query(SalesMessage).filter_by(provider_message_id='bounded-replay').count() == 1


def test_postgres_slow_job_releases_lock_while_api_accepts_next_inbound(postgres_case, monkeypatch):
    engine, (_, conversation_id, _) = postgres_case
    app = application(engine, conversation_id, monkeypatch)
    entered, release = Event(), Event()
    async def slow_model_job(job_id):
        assert job_id == 'synthetic-only'
        with bounded(Session(engine)) as db:
            db.query(SalesConversation).filter_by(id=conversation_id).with_for_update().one()
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            db.commit()
    async def scenario():
        job = asyncio.create_task(asyncio.to_thread(live_worker._isolated_job, slow_model_job, 'synthetic-only'))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                request = asyncio.create_task(client.post('/sms', data={'MessageSid':'during-model', 'To':'+15550100002', 'From':'+15550100001', 'Body':'Show plans'}))
                await asyncio.sleep(.1)
                assert not request.done()
                assert (await asyncio.wait_for(client.get('/probe'), timeout=1)).status_code == 200
                release.set()
                assert (await asyncio.wait_for(request, timeout=5)).status_code == 200
        finally:
            release.set()
            await asyncio.wait_for(job, timeout=5)
    asyncio.run(scenario())
    with Session(engine) as db:
        assert db.query(SalesInboundJob).count() == 1
