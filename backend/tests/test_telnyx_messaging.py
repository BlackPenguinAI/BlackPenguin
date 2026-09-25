import base64
import importlib.util
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.core.secret_store import decrypt_secret, encrypt_secret
from app.db.postgres import Base, get_db
from app.integrations.messaging_gateway import default_provider, live_provider
from app.integrations.telnyx_client import validate_telnyx_signature
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_agent.live_service import get_or_create_live_conversation
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_agent.provider_router import telnyx_router
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.models import (
    MessagingRoutingConfig, TelnyxCompanyConfig, TelnyxConfig, TwilioConfig,
)
from app.modules.system_settings.schemas import TelnyxCompanyConfigUpdate, TelnyxConfigUpdate
from app.modules.system_settings.services import (
    telnyx_config_response, update_default_provider, update_telnyx_company_config,
    update_telnyx_config, verify_telnyx_company_config, verify_telnyx_config,
)


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _public_key() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(raw).decode()


def _company_project_lead(db, *, company_name: str, sender_phone: str, lead_phone: str):
    company = Company(name=company_name); db.add(company); db.flush()
    project = Project(company_id=company.id, name=f"{company_name} Project"); db.add(project); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead", phone=lead_phone,
        source="meta", platform="meta",
    )
    db.add(lead); db.flush()
    config = TelnyxCompanyConfig(
        company_id=company.id, messaging_profile_id=f"profile-{company_name}",
        from_phone_number=sender_phone, regulatory_status="approved",
        verification_status="verified", live_sms_enabled=True,
    )
    db.add(config); db.flush()
    return company, project, lead, config


def test_telnyx_global_api_key_is_encrypted_write_only_and_changes_force_reverification():
    db = _db(); _, public_key = _public_key()
    config = update_telnyx_config(db, TelnyxConfigUpdate(
        api_key="KEY-secret-value", webhook_public_key=public_key,
    ))
    response = telnyx_config_response(config)
    assert decrypt_secret(config.api_key_ciphertext) == "KEY-secret-value"
    assert config.verification_status == "pending" and config.live_sms_enabled is False
    assert response["api_key_configured"] is True and response["api_key_hint"] == "alue"
    assert "api_key" not in response and "webhook_public_key" not in response
    assert "messaging_profile_id" not in response and "from_phone_number" not in response


def test_telnyx_signature_accepts_exact_body_and_rejects_tampering():
    private, public_key = _public_key()
    payload = b'{"data":{"id":"event-1"}}'
    timestamp = str(int(time.time()))
    signature = base64.b64encode(private.sign(timestamp.encode() + b"|" + payload)).decode()
    assert validate_telnyx_signature(public_key=public_key, payload=payload, signature=signature, timestamp=timestamp)
    assert not validate_telnyx_signature(public_key=public_key, payload=payload + b" ", signature=signature, timestamp=timestamp)


def test_global_verification_rejects_an_invalid_webhook_public_key():
    db = _db()
    db.add(TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), webhook_public_key="not-an-ed25519-key",
        verification_status="pending",
    )); db.commit()
    with pytest.raises(HTTPException, match="could not be verified"):
        verify_telnyx_config(db)
    assert db.query(TelnyxConfig).one().verification_status == "failed"


def test_global_and_company_verification_are_independent():
    db = _db(); _, public_key = _public_key()
    db.add(TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), webhook_public_key=public_key,
        verification_status="pending", live_sms_enabled=False,
    ))
    company = Company(name="Tenant"); db.add(company); db.flush()
    db.add(TelnyxCompanyConfig(
        company_id=company.id, messaging_profile_id="profile-1", from_phone_number="+13055550142",
        regulatory_status="approved",
    )); db.commit()
    balance = Mock(); balance.raise_for_status.return_value = None
    with patch("app.modules.system_settings.services.httpx.get", return_value=balance):
        platform = verify_telnyx_config(db)
    assert platform.verification_status == "verified"
    profile = Mock(); profile.raise_for_status.return_value = None
    profile.json.return_value = {"data": {
        "id": "profile-1",
        "webhook_url": "https://blackpenguin.ai/api/v1/webhooks/telnyx/messaging",
    }}
    number = Mock(); number.raise_for_status.return_value = None
    number.json.return_value = {"data": [{
        "id": "number-id-1", "phone_number": "+13055550142",
        "messaging_profile_id": "profile-1",
    }]}
    with patch("app.modules.system_settings.services.httpx.get", side_effect=[profile, number]):
        sender = verify_telnyx_company_config(db, company.id)
    assert sender.verification_status == "verified"
    assert sender.telnyx_phone_number_id == "number-id-1"


def test_company_sender_and_profile_cannot_be_shared_across_tenants():
    db = _db()
    first = Company(name="First"); second = Company(name="Second")
    db.add_all([first, second]); db.commit()
    update_telnyx_company_config(db, first.id, TelnyxCompanyConfigUpdate(
        messaging_profile_id="profile-first", from_phone_number="+13055550101",
        regulatory_status="approved",
    ))
    with pytest.raises(HTTPException, match="already assigned"):
        update_telnyx_company_config(db, second.id, TelnyxCompanyConfigUpdate(
            messaging_profile_id="profile-first", from_phone_number="+13055550102",
        ))
    with pytest.raises(HTTPException, match="already assigned"):
        update_telnyx_company_config(db, second.id, TelnyxCompanyConfigUpdate(
            messaging_profile_id="profile-second", from_phone_number="+13055550101",
        ))


def test_same_lead_phone_uses_distinct_threads_for_distinct_companies():
    db = _db(); _, public_key = _public_key()
    db.add_all([
        TelnyxConfig(
            api_key_ciphertext=encrypt_secret("KEY"), webhook_public_key=public_key,
            verification_status="verified", live_sms_enabled=True,
        ),
        MessagingRoutingConfig(default_provider="telnyx"),
    ]); db.flush()
    first, _, first_lead, _ = _company_project_lead(
        db, company_name="First", sender_phone="+13055550101", lead_phone="+13055550999",
    )
    second, _, second_lead, _ = _company_project_lead(
        db, company_name="Second", sender_phone="+13055550102", lead_phone="+13055550999",
    )
    db.commit()
    first_conversation, _ = get_or_create_live_conversation(db, first_lead)
    second_conversation, _ = get_or_create_live_conversation(db, second_lead)
    assert first_conversation.company_id == first.id
    assert second_conversation.company_id == second.id
    assert first_conversation.provider_thread_key == "telnyx:+13055550101:+13055550999"
    assert second_conversation.provider_thread_key == "telnyx:+13055550102:+13055550999"


def test_default_telnyx_requires_global_and_at_least_one_company_sender():
    db = _db(); _, public_key = _public_key()
    db.add_all([
        MessagingRoutingConfig(default_provider="twilio"),
        TelnyxConfig(
            api_key_ciphertext=encrypt_secret("KEY"), webhook_public_key=public_key,
            verification_status="verified", live_sms_enabled=True,
        ),
    ]); db.commit()
    with pytest.raises(HTTPException, match="Verify and enable"):
        update_default_provider(db, "telnyx")
    company, _, _, _ = _company_project_lead(
        db, company_name="Ready", sender_phone="+13055550142", lead_phone="+13055550999",
    )
    db.commit()
    assert update_default_provider(db, "telnyx").default_provider == "telnyx"
    assert default_provider(db) == "telnyx"
    assert live_provider(db, company_id=company.id) == "telnyx"


def test_signed_webhook_routes_by_destination_number_and_company():
    db = _db(); private, public_key = _public_key()
    db.add(TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), webhook_public_key=public_key,
        verification_status="verified", live_sms_enabled=True,
    )); db.flush()
    company, project, lead, _ = _company_project_lead(
        db, company_name="Tenant", sender_phone="+18573824206", lead_phone="+13055550142",
    )
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="sms", provider="telnyx",
        provider_thread_key="telnyx:+18573824206:+13055550142", is_paused=True,
    )
    db.add(conversation); db.commit()
    envelope = {"data": {"id": "event-1", "event_type": "message.received", "payload": {
        "id": "message-1", "text": "I want a visit",
        "from": {"phone_number": "+13055550142"},
        "to": [{"phone_number": "+18573824206"}],
    }}}
    body = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = base64.b64encode(private.sign(timestamp.encode() + b"|" + body)).decode()
    app = FastAPI(); app.include_router(telnyx_router, prefix="/webhooks/telnyx")
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).post(
        "/webhooks/telnyx/messaging", content=body,
        headers={
            "Content-Type": "application/json",
            "telnyx-signature-ed25519": signature,
            "telnyx-timestamp": timestamp,
        },
    )
    assert response.status_code == 200
    message = db.query(SalesMessage).one()
    assert message.conversation_id == conversation.id and message.content == "I want a visit"


def test_tenant_migration_is_repeatable_on_current_schema(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260925_telnyx_company_senders.py"
    spec = importlib.util.spec_from_file_location("telnyx_tenant_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite://"); Base.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade(); migration.upgrade()
        tables = set(connection.dialect.get_table_names(connection))
        columns = {item["name"] for item in connection.dialect.get_columns(connection, "telnyx_company_configurations")}
    assert "telnyx_company_configurations" in tables
    assert {"company_id", "messaging_profile_id", "from_phone_number", "regulatory_status"}.issubset(columns)


def test_twilio_remains_default_for_existing_installations():
    db = _db(); db.add(TwilioConfig(verification_status="verified", live_sms_enabled=True)); db.commit()
    assert default_provider(db) == "twilio"
