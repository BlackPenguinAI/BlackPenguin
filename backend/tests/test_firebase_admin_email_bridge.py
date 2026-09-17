from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.integrations import firebase_admin_client
from app.modules.system_settings import services


def test_email_enqueue_without_bridge_uses_email_specific_error(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_URL", "")
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_SECRET", "")

    with pytest.raises(HTTPException) as error:
        firebase_admin_client.enqueue_email(
            project_id="blackpenguinai",
            document_id="transport-test",
            recipient="test@example.com",
            subject="Transport test",
            text="Test",
            html="<p>Test</p>",
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "FIREBASE_ADMIN_EMAIL_UNAVAILABLE"
    assert "deletion" not in error.value.detail["message"].lower()


def test_transport_verification_preserves_clean_bridge_error(monkeypatch):
    config = SimpleNamespace(
        project_id="blackpenguinai",
        appointment_from_name="Black Penguin",
        appointment_from_email="info@blackpenguin.ai",
        appointment_reply_to="info@blackpenguin.ai",
        appointment_mail_collection="mail",
        appointment_transport_status="pending",
        appointment_transport_error=None,
    )
    db = SimpleNamespace(commit=lambda: None, refresh=lambda value: None)
    monkeypatch.setattr(services, "get_firebase_config", lambda unused_db: config)
    unavailable = HTTPException(
        status_code=409,
        detail={
            "code": "FIREBASE_ADMIN_EMAIL_UNAVAILABLE",
            "message": "Configure the Firebase Admin bridge for appointment email.",
        },
    )

    with patch("app.integrations.firebase_admin_client.enqueue_email", side_effect=unavailable):
        with pytest.raises(HTTPException) as error:
            services.verify_appointment_email_transport(db, "test@example.com")

    assert error.value.status_code == 409
    assert config.appointment_transport_status == "failed"
    assert config.appointment_transport_error == "Configure the Firebase Admin bridge for appointment email."


def test_email_enqueue_calls_mail_endpoint_when_bridge_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_URL", "https://bridge.example")
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_SECRET", "shared-secret")
    response = SimpleNamespace(
        is_error=False,
        status_code=200,
        json=lambda: {"status": "queued", "document_id": "transport-test"},
    )

    with patch("app.integrations.firebase_admin_client.httpx.post", return_value=response) as request:
        result = firebase_admin_client.enqueue_email(
            project_id="blackpenguinai",
            document_id="transport-test",
            recipient="test@example.com",
            subject="Transport test",
            text="Test",
            html="<p>Test</p>",
        )

    assert result["status"] == "queued"
    assert request.call_args.args[0] == "https://bridge.example/mail/enqueue"
