"""Offline checks for the API/worker boundary (no provider or model calls)."""
import asyncio
import inspect
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from app.modules.sales_agent import live_worker, provider_router


def test_provider_database_handlers_are_sync_routes():
    for handler in (provider_router.twilio_inbound_sms, provider_router.twilio_message_status, provider_router.telnyx_messaging_webhook):
        assert not inspect.iscoroutinefunction(handler)
    assert inspect.iscoroutinefunction(provider_router._body_bytes)
    assert inspect.iscoroutinefunction(provider_router._form_params)


def test_model_job_owns_private_loop_without_blocking_api():
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    async def handler(job_id):
        assert job_id == 'offline-job'
        assert threading.get_ident() != main_thread
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
    async def scenario():
        task = asyncio.create_task(asyncio.to_thread(live_worker._isolated_job, handler, 'offline-job'))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await asyncio.wait_for(asyncio.sleep(.01), timeout=.5)
            assert not task.done()
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=2)
    asyncio.run(scenario())


@pytest.mark.parametrize('code,expected', [('55P03', 503), ('23505', None)])
def test_provider_rolls_back_and_only_lock_timeout_is_retryable(monkeypatch, code, expected):
    from app.modules.sales_agent import concurrency
    monkeypatch.setattr(concurrency, 'bounded', lambda db: db)
    rollbacks = []
    db = SimpleNamespace(rollback=lambda: rollbacks.append(True))
    dependency = provider_router._provider_db(db)
    assert next(dependency) is db
    error = OperationalError('synthetic statement', {}, SimpleNamespace(pgcode=code))
    with pytest.raises(HTTPException if expected else OperationalError) as caught:
        dependency.throw(error)
    assert rollbacks == [True]
    if expected:
        assert caught.value.status_code == expected
        assert caught.value.headers == {'Retry-After': '2'}


def test_job_wrapper_does_not_reopen_transaction_before_child_turn(monkeypatch):
    from test_live_sales_agent import _db
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent import live_service
    from app.modules.sales_agent.models import SalesConversation, SalesInboundJob, SalesMessage
    db = _db()
    company = Company(name='Offline concurrency'); db.add(company); db.flush()
    project = Project(company_id=company.id, name='Offline project'); db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name='Synthetic lead', phone='+15550100001', source='manual')
    db.add(lead); db.flush()
    conversation = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id, channel='sms', provider='telnyx')
    db.add(conversation); db.flush()
    message = SalesMessage(conversation_id=conversation.id, channel='sms', direction='inbound', role='user', content='Hello', status='received')
    db.add(message); db.flush()
    job = SalesInboundJob(conversation_id=conversation.id, message_id=message.id, status='processing')
    db.add(job); db.flush()
    ids = job.id, conversation.id, message.id
    db.commit()
    monkeypatch.setattr(live_service, 'SessionLocal', lambda: db)
    checked = []
    async def child(conversation_id, message_id):
        assert (conversation_id, message_id) == ids[1:]
        assert not db.in_transaction()
        checked.append(True)
    monkeypatch.setattr(live_service, 'process_live_inbound', child)
    asyncio.run(live_service.process_live_inbound_job(ids[0]))
    assert checked == [True]
