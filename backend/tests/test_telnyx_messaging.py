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
from app.db.postgres import Base
from app.db.postgres import get_db
from app.integrations.messaging_gateway import default_provider
from app.integrations.telnyx_client import validate_telnyx_signature
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_agent.live_service import get_or_create_live_conversation
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_agent.provider_router import telnyx_router
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.models import MessagingRoutingConfig, TelnyxConfig, TwilioConfig
from app.modules.system_settings.schemas import TelnyxConfigUpdate
from app.modules.system_settings.services import (
    telnyx_config_response, update_default_provider, update_telnyx_config, verify_telnyx_config,
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


def test_telnyx_api_key_is_encrypted_write_only_and_changes_force_reverification():
    db = _db(); _, public_key = _public_key()
    config = update_telnyx_config(db, TelnyxConfigUpdate(
        api_key="KEY-secret-value", messaging_profile_id="profile-1",
        from_phone_number="+1 (305) 555-0142", webhook_public_key=public_key,
    ))
    response = telnyx_config_response(config)
    assert decrypt_secret(config.api_key_ciphertext) == "KEY-secret-value"
    assert config.from_phone_number == "+13055550142"
    assert config.verification_status == "pending" and config.live_sms_enabled is False
    assert response["api_key_configured"] is True and response["api_key_hint"] == "alue"
    assert "api_key" not in response and "webhook_public_key" not in response


def test_telnyx_signature_accepts_exact_body_and_rejects_tampering():
    private, public_key = _public_key()
    payload = b'{"data":{"id":"event-1"}}'
    timestamp = str(int(time.time()))
    signature = base64.b64encode(private.sign(timestamp.encode() + b"|" + payload)).decode()
    assert validate_telnyx_signature(public_key=public_key, payload=payload, signature=signature, timestamp=timestamp)
    assert not validate_telnyx_signature(public_key=public_key, payload=payload + b" ", signature=signature, timestamp=timestamp)


def test_default_provider_requires_verified_live_configuration():
    db = _db()
    db.add_all([MessagingRoutingConfig(default_provider="twilio"), TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), messaging_profile_id="profile-1",
        from_phone_number="+13055550142", webhook_public_key="key",
        verification_status="verified", live_sms_enabled=False,
    )]); db.commit()
    with pytest.raises(HTTPException, match="Verify and enable"):
        update_default_provider(db, "telnyx")
    telnyx = db.query(TelnyxConfig).one(); telnyx.live_sms_enabled = True; db.commit()
    assert update_default_provider(db, "telnyx").default_provider == "telnyx"
    assert default_provider(db) == "telnyx"


def test_telnyx_verification_checks_profile_and_number():
    db = _db(); _, public_key = _public_key()
    db.add(TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), messaging_profile_id="profile-1",
        from_phone_number="+13055550142", webhook_public_key=public_key,
    )); db.commit()
    profile = Mock(); profile.raise_for_status.return_value = None; profile.json.return_value = {"data": {"id": "profile-1"}}
    number = Mock(); number.raise_for_status.return_value = None; number.json.return_value = {"data": [{"phone_number": "+13055550142", "messaging_profile_id": "profile-1"}]}
    with patch("app.modules.system_settings.services.httpx.get", side_effect=[profile, number]):
        verified = verify_telnyx_config(db)
    assert verified.verification_status == "verified" and verified.verified_at is not None


def test_telnyx_migration_is_repeatable_on_current_schema(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260925_telnyx_messaging_routing.py"
    spec = importlib.util.spec_from_file_location("telnyx_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite://"); Base.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade(); migration.upgrade()
        tables = set(connection.dialect.get_table_names(connection))
        conversation_columns = {item["name"] for item in connection.dialect.get_columns(connection, "sales_conversations")}
    assert {"telnyx_configurations", "messaging_routing_configurations"}.issubset(tables)
    assert "provider" in conversation_columns


def test_twilio_remains_default_for_existing_installations():
    db = _db(); db.add(TwilioConfig(verification_status="verified", live_sms_enabled=True)); db.commit()
    assert default_provider(db) == "twilio"


def test_existing_conversation_stays_pinned_after_default_provider_switch():
    db = _db(); company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project"); db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Lead", phone="+13055550142", source="meta", platform="meta")
    db.add(lead); db.flush()
    db.add_all([
        TwilioConfig(from_phone_number="+18573824206", verification_status="verified", live_sms_enabled=True),
        MessagingRoutingConfig(default_provider="twilio"),
    ]); db.commit()
    conversation, created = get_or_create_live_conversation(db, lead)
    db.commit()
    assert created is True and conversation.provider == "twilio"
    db.query(MessagingRoutingConfig).one().default_provider = "telnyx"; db.commit()
    pinned, created_again = get_or_create_live_conversation(db, lead, provider="telnyx")
    assert created_again is False and pinned.id == conversation.id and pinned.provider == "twilio"


def test_signed_telnyx_inbound_webhook_reaches_the_pinned_conversation():
    db = _db(); private, public_key = _public_key()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project"); db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Lead", phone="+13055550142", source="meta", platform="meta")
    db.add(lead); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="sms", provider="telnyx",
        provider_thread_key="telnyx:+18573824206:+13055550142", is_paused=True,
    )
    db.add_all([conversation, TelnyxConfig(
        api_key_ciphertext=encrypt_secret("KEY"), messaging_profile_id="profile-1",
        from_phone_number="+18573824206", webhook_public_key=public_key,
        verification_status="verified", live_sms_enabled=True,
    )]); db.commit()
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
        headers={"Content-Type": "application/json", "telnyx-signature-ed25519": signature, "telnyx-timestamp": timestamp},
    )
    assert response.status_code == 200
    message = db.query(SalesMessage).one()
    assert message.conversation_id == conversation.id and message.content == "I want a visit"
