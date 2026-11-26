"""Synthetic E2E scenario helpers; never loaded by the production worker.

Use only the real_lane test fixture (private database, provider double, scoped
readiness override). No real contact, Calendar credential, or share destination.
"""
import asyncio
import os
import secrets
import pytest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4


@pytest.fixture
def hei06_lane_engine():
    # Separate SessionLocal inside the private ASGI endpoint; a shared
    # in-memory connection permits sequential API/SDK threads, never two
    # concurrent transactions. Real concurrency is tested on PostgreSQL.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread':False})
    try:
        yield engine
    finally:
        engine.dispose()


def seed_catalog(lane, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.modules.projects.models import (ProjectPropertyType, ProjectOnboardingSource,
        ProjectSourceKind, ProjectSourceStatus, ProjectSalesAsset)
    from app.modules.hermes_sales_core.staff_models import HermesGlobalSettings, HermesGlobalVersion
    from app.modules.hermes_sales_core.staff_config import DEFAULT_MODEL
    db = lane.db
    assert db.get_bind().dialect.name == 'sqlite'
    assert db.get_bind().url.database == ':memory:'
    from app.db import postgres
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr(postgres,'SessionLocal',sessionmaker(bind=db.get_bind(),autoflush=False))
    monkeypatch.setenv('HERMES_INTERNAL_TOKEN',secrets.token_hex(32))
    assert db.get(HermesGlobalSettings, 'global').configuration['model'] == DEFAULT_MODEL
    assert db.get(HermesGlobalVersion, 'version').configuration['model'] == DEFAULT_MODEL
    monkeypatch.setattr(settings, 'PROJECT_UPLOAD_ROOT', str(tmp_path))
    monkeypatch.setattr(settings, 'PUBLIC_APP_URL', 'https://example.invalid')
    timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
    for ref, name, price, sort in [('van', 'Van Buren', 325000, 0), ('oak', 'Oakwood', 340000, 1)]:
        db.add(ProjectPropertyType(id=ref, project_id='project', name=name, review_status='confirmed',
            bedrooms=3, bathrooms=2, starting_price=price, currency='USD', available_units=2,
            inventory_updated_at=timestamp, sort_order=sort))
    db.flush()
    content = b'%PDF-1.4\n% HEI06 synthetic brochure; no customer data\n%%EOF'
    (tmp_path/'brochure.pdf').write_bytes(content)
    db.add(ProjectOnboardingSource(id='brochure-source', project_id='project', kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY, name='Van Buren brochure', mime_type='application/pdf',
        storage_path='brochure.pdf', is_encrypted=False, content_hash=sha256(content).hexdigest()))
    db.flush()
    db.add(ProjectSalesAsset(id='brochure-van', company_id='co', project_id='project', property_type_id='van',
        source_id='brochure-source', asset_type='brochure', content_tags=['brochure'],
        display_name='Van Buren brochure', approval_status='approved', approved_at=timestamp,
        allowed_channels=['sms','whatsapp']))
    db.commit()


def run_claimed(lane, job_id):
    # Actual authenticated FastAPI endpoint, using ASGI transport rather than
    # network sockets. Separate SessionLocal and API transactions are real;
    # provider calls are still doubled by the isolated fixture.
    async def prepare(identifier, run_id):
        import httpx
        assert not lane.db.in_transaction()
        lane.sdk_calls.append(run_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=lane.sdk_service.app),
                                     base_url='http://bp-hermes:8080',trust_env=False) as client:
            response = await client.post('/internal/prepare',
                json={'job_id':identifier,'run_id':run_id},
                headers={'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']})
        assert response.status_code==200
        assert response.json()=={'run_id':run_id,'status':'draft_ready'}
    asyncio.run(lane.job.run_job(lane.db, job_id, prepare=prepare))
    job = lane.db.get(lane.Job, job_id)
    assert job.status == 'processed'
    inbound = lane.db.get(lane.Message, job.message_id)
    assert (inbound.metadata_json or {}).get('agent_turn_status') == 'answered'
    lane.db.commit()
    return job.message_id


def first_input(lane, message):
    row = lane.db.get(lane.Message, 'inbound')
    row.content = message
    from app.modules.hermes_sales_core.engine_boundary import transition
    transition(lane.db, lane.db.get(lane.Conversation, 'conversation'), row, row.metadata_json['sales_engine_pin'])
    lane.db.commit()
    return run_claimed(lane, 'job')


def next_input(lane, message):
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.engine_router import resolve
    from app.modules.hermes_sales_core.engine_boundary import transition
    db = lane.db
    conversation = db.get(lane.Conversation, 'conversation')
    mid, jid = str(uuid4()), str(uuid4())
    provider_id = 'synthetic-' + mid
    last = db.query(lane.Message).order_by(lane.Message.created_at.desc()).first()
    now = max(datetime.now(timezone.utc).replace(tzinfo=None), last.created_at + timedelta(microseconds=1))
    row = lane.Message(id=mid, conversation_id=conversation.id, channel='sms', direction='inbound',
        role='user', content=message, status='received', provider_message_id=provider_id, created_at=now,
        metadata_json={'lead_id':'lead','project_id':'project'})
    db.add(row); db.flush()
    assert continuity.received(db, conversation, row)
    pin = resolve(db, conversation, 'telnyx:' + provider_id)
    assert pin['engine'] == 'hermes'
    row.metadata_json = {**row.metadata_json, 'sales_engine_pin':pin}
    transition(db, conversation, row, pin)
    db.add(lane.Job(id=jid, conversation_id=conversation.id, message_id=mid, status='processing', attempt_number=1))
    db.commit()
    return run_claimed(lane, jid), jid


def state(lane):
    value = lane.load(lane.db, lane.scope).data
    lane.db.commit()
    return value


def tools_for(lane, message_id):
    from app.modules.sales_agent.models import AgentRun
    runs = lane.db.query(AgentRun).filter_by(conversation_id='conversation').all()
    matching = [r for r in runs if (r.input_snapshot or {}).get('message_id') == message_id]
    assert len(matching) == 1 and matching[0].status == 'completed'
    result = {x['tool'] for x in matching[0].output_snapshot['tool_observations'] if x['status']=='executed'}
    lane.db.commit()
    return result


def verify_material_and_replay(lane, mid, jid):
    from app.modules.projects.models import SalesAssetShare
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    shares = lane.db.query(SalesAssetShare).all()
    assert len(shares) == 1 and shares[0].sales_asset_id == 'brochure-van' and shares[0].outbound_message_id
    op = lane.db.query(HermesSalesOperation).filter_by(inbound_message_id=mid, operation_type='material').one()
    assert op.status == 'completed' and op.result_json['status'] == 'provider_accepted'
    assert 'get_unit_media' in tools_for(lane, mid)
    assert '/projects/a/' in lane.calls[-1]
    calls, sdk_calls = len(lane.calls), len(lane.sdk_calls)
    lane.db.get(lane.Job, jid).status = 'processing'
    lane.db.commit()
    run_claimed(lane, jid)
    assert len(lane.calls) == calls and len(lane.sdk_calls) == sdk_calls
    assert lane.db.query(SalesAssetShare).count() == 1
    lane.db.commit()
