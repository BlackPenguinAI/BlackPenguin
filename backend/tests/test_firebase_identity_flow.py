from datetime import datetime, timedelta
import logging
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.core.middleware import MultiTenantMiddleware
from app.core.security import verify_password
from app.db.postgres import Base
from app.modules.auth.router import (
    ChangePasswordPayload,
    CompleteInvitationPayload,
    FirebaseActionCodePayload,
    change_password,
    complete_firebase_invitation,
    inspect_firebase_action,
)
from app.modules.companies.models import Company
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.system_settings.models import FirebaseConfig
from app.modules.system_settings.schemas import FirebaseConfigUpdate
from app.modules.system_settings.services import firebase_config_response, update_firebase_config
from app.modules.users.models import User, UserAuthStatus, UserInvitation, UserRole
from app.modules.users.services import invite_tenant_user
from app.modules.users.services import resend_user_activation


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _company(db):
    plan = SubscriptionPlan(
        name="Firebase Test", max_projects=3, max_assistants=2,
        max_mkt_users=2, max_sales_users=2, is_active=True,
    )
    company = Company(name="Northstar Homes", plan=plan, is_active=True)
    db.add_all([plan, company]); db.commit(); db.refresh(company)
    return company


def _verified_firebase(db):
    config = FirebaseConfig(
        project_id="bp-test", api_key="public-api-key",
        auth_domain="bp-test.firebaseapp.com", is_enabled=True,
        auth_mode="rest", verification_status="verified",
        action_handler_url="https://blackpenguin.ai/activate-account",
    )
    db.add(config); db.commit()
    return config


def test_invitation_provisions_firebase_without_an_administrator_password():
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        with patch("app.integrations.firebase_client.create_identity") as create_identity, patch(
            "app.integrations.firebase_client.send_password_action_email"
        ) as send_email:
            create_identity.return_value.uid = "firebase-sales"
            user = invite_tenant_user(
                db, company_id=company.id, email="Sales@Northstar.example",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
                timezone="America/New_York", invited_by_user_id=None,
            )
        assert user.auth_status == UserAuthStatus.INVITED
        assert user.firebase_uid == "firebase-sales"
        assert user.invitation_sent_at is not None
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert invitation.status == "accepted_by_provider"
        assert invitation.send_attempts == 1
        assert invitation.last_attempt_at is not None
        assert invitation.provisioning_secret_ciphertext is None
        create_identity.assert_called_once()
        send_email.assert_called_once_with(db, "sales@northstar.example")
    finally:
        db.close(); engine.dispose()


def test_activation_is_one_time_and_returns_a_tenant_session():
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="sales@example.com", first_name="Sam",
            last_name="Seller", role=UserRole.SALES, hashed_password="not-used",
            firebase_uid="firebase-sales", auth_status=UserAuthStatus.INVITED,
            is_active=True,
        )
        db.add(user); db.flush()
        db.add(UserInvitation(
            user_id=user.id, status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
        db.commit()
        with patch("app.integrations.firebase_client.verify_password_action_code", return_value=user.email), patch(
            "app.integrations.firebase_client.confirm_password_action", return_value=user.email
        ), patch(
            "app.integrations.firebase_client.sign_in_with_password",
            return_value={"localId": user.firebase_uid},
        ):
            response = complete_firebase_invitation(
                CompleteInvitationPayload(oob_code="valid-action-code", new_password="Secure#Pass1"),
                db,
            )
        db.refresh(user)
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert response["role"] == UserRole.SALES
        assert response["access_token"]
        assert user.auth_status == UserAuthStatus.ACTIVE
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None
    finally:
        db.close(); engine.dispose()


def test_firebase_rest_configuration_does_not_require_a_service_account():
    engine, db = _db()
    try:
        config = update_firebase_config(db, FirebaseConfigUpdate(
            project_id="bp-test", api_key="public-api-key",
            auth_domain="bp-test.firebaseapp.com",
            action_handler_url="https://blackpenguin.ai/activate-account",
        ))
        response = firebase_config_response(config)
        assert config.service_account_ciphertext is None
        assert response["auth_mode"] == "rest"
        assert "credentials_configured" not in response
        assert "credentials_hint" not in response
    finally:
        db.close(); engine.dispose()


def test_firebase_invitation_failure_is_logged_with_trace_context_and_resend_uses_424(caplog):
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        with caplog.at_level(logging.INFO), patch(
            "app.integrations.firebase_client.create_identity",
            side_effect=HTTPException(status_code=422, detail="OPERATION_NOT_ALLOWED"),
        ):
            user = invite_tenant_user(
                db, company_id=company.id, email="sales@northstar.example",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
            )
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert user.auth_status == UserAuthStatus.PROVISIONING_FAILED
        assert invitation.last_error == "OPERATION_NOT_ALLOWED"
        assert any(
            "Firebase invitation failed" in record.message
            and f"company_id={company.id}" in record.message
            and f"user_id={user.id}" in record.message
            and f"invitation_id={invitation.id}" in record.message
            and "phase=create_identity" in record.message
            and "error_code=OPERATION_NOT_ALLOWED" in record.message
            for record in caplog.records
        )

        invitation.last_attempt_at = datetime.utcnow() - timedelta(minutes=2)
        db.commit()
        with patch(
            "app.integrations.firebase_client.create_identity",
            side_effect=HTTPException(status_code=422, detail="OPERATION_NOT_ALLOWED"),
        ), pytest.raises(HTTPException) as exc_info:
            resend_user_activation(db, user=user)
        assert exc_info.value.status_code == 424
        assert exc_info.value.detail.endswith("OPERATION_NOT_ALLOWED")
    finally:
        db.close(); engine.dispose()


def test_only_signed_public_flows_bypass_global_bearer_requirement():
    app = FastAPI()
    app.add_middleware(MultiTenantMiddleware)

    @app.get("/api/v1/sales/calendar/google/callback")
    def callback():
        return {"ok": True}

    @app.get("/api/v1/sales/public/meetings/meeting-1.ics")
    def invite():
        return {"ok": True}

    @app.get("/api/v1/sales/calendar/google/connect")
    def connect():
        return {"should": "remain protected"}

    client = TestClient(app)
    assert client.get("/api/v1/sales/calendar/google/callback").status_code == 200
    assert client.get("/api/v1/sales/public/meetings/meeting-1.ics").status_code == 200
    protected = client.get("/api/v1/sales/calendar/google/connect")
    assert protected.status_code == 401
    assert protected.json()["detail"] == "No autorizado. Token Bearer ausente."


def test_authenticated_firebase_user_changes_password_in_identity_provider():
    engine, db = _db()
    try:
        company = _company(db)
        db.add(FirebaseConfig(
            project_id="bp-test", api_key="public-key", is_enabled=True,
            auth_mode="rest", action_handler_url="https://blackpenguin.ai/activate-account",
        ))
        user = User(
            company_id=company.id, email="sales@example.com", first_name="Sam",
            role=UserRole.SALES, hashed_password="legacy-placeholder",
            firebase_uid="firebase-sales", auth_status=UserAuthStatus.ACTIVE,
            is_active=True,
        )
        db.add(user); db.commit()
        with patch(
            "app.integrations.firebase_client.sign_in_with_password",
            return_value={"localId": user.firebase_uid, "idToken": "firebase-id-token"},
        ) as sign_in, patch("app.integrations.firebase_client.update_password") as update_password:
            response = change_password(
                ChangePasswordPayload(current_password="OldSecure#1", new_password="NewSecure#2"),
                db,
                user,
            )
        assert response["detail"] == "Password updated successfully."
        sign_in.assert_called_once_with(db, user.email, "OldSecure#1")
        update_password.assert_called_once_with(db, id_token="firebase-id-token", password="NewSecure#2")
        assert verify_password("NewSecure#2", user.hashed_password)
    finally:
        db.close(); engine.dispose()


def test_active_user_can_use_the_same_firebase_handler_for_password_recovery():
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="active@example.com", first_name="Avery",
            role=UserRole.SALES, hashed_password="not-used", firebase_uid="firebase-active",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        db.add(user); db.commit()
        with patch("app.integrations.firebase_client.verify_password_action_code", return_value=user.email):
            preview = inspect_firebase_action(FirebaseActionCodePayload(oob_code="reset-action-code"), db)
        assert preview["flow"] == "password_reset"
        with patch("app.integrations.firebase_client.verify_password_action_code", return_value=user.email), patch(
            "app.integrations.firebase_client.confirm_password_action", return_value=user.email,
        ), patch(
            "app.integrations.firebase_client.sign_in_with_password", return_value={"localId": user.firebase_uid},
        ):
            response = complete_firebase_invitation(
                CompleteInvitationPayload(oob_code="reset-action-code", new_password="ResetSecure#3"), db,
            )
        assert response["access_token"]
        assert db.query(UserInvitation).filter_by(user_id=user.id).count() == 0
        assert user.auth_status == UserAuthStatus.ACTIVE
    finally:
        db.close(); engine.dispose()


def test_firebase_rest_creates_and_looks_up_an_identity_without_admin_sdk():
    engine, db = _db()
    try:
        _verified_firebase(db)

        class Response:
            is_error = False
            def __init__(self, payload): self.payload = payload
            def json(self): return self.payload

        with patch("app.integrations.firebase_client.httpx.post", side_effect=[
            Response({"localId": "firebase-uid", "idToken": "token"}),
            Response({"users": [{"localId": "firebase-uid", "email": "sales@example.com"}]}),
        ]) as post:
            from app.integrations.firebase_client import create_identity, verify_id_token
            identity = create_identity(db, email="sales@example.com", password="Temporary#123")
            verified = verify_id_token(db, "firebase-token")
        assert identity.uid == "firebase-uid"
        assert verified["uid"] == "firebase-uid"
        assert post.call_args_list[0].args[0].endswith("accounts:signUp")
        assert post.call_args_list[1].args[0].endswith("accounts:lookup")
    finally:
        db.close(); engine.dispose()


def test_firebase_rest_rejection_logs_safe_provider_details(caplog):
    engine, db = _db()
    try:
        _verified_firebase(db)

        class Response:
            is_error = True
            status_code = 400
            def json(self):
                return {"error": {"message": "OPERATION_NOT_ALLOWED"}}

        with caplog.at_level(logging.ERROR), patch(
            "app.integrations.firebase_client.httpx.post", return_value=Response(),
        ), pytest.raises(HTTPException):
            from app.integrations.firebase_client import create_identity
            create_identity(db, email="sales@example.com", password="DoNotLog#123")

        combined = "\n".join(record.message for record in caplog.records)
        assert "endpoint=accounts:signUp" in combined
        assert "project_id=bp-test" in combined
        assert "http_status=400" in combined
        assert "error_code=OPERATION_NOT_ALLOWED" in combined
        assert "public-api-key" not in combined
        assert "DoNotLog#123" not in combined
    finally:
        db.close(); engine.dispose()


def test_resend_reports_provider_failure_instead_of_false_success():
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        user = User(
            company_id=company.id, email="retry@example.com", first_name="Riley",
            role=UserRole.SALES, hashed_password="not-used", firebase_uid="firebase-retry",
            auth_status=UserAuthStatus.PROVISIONING_FAILED, is_active=True,
        )
        db.add(user); db.flush()
        db.add(UserInvitation(
            user_id=user.id, status="delivery_failed", send_attempts=1,
            last_attempt_at=datetime.utcnow() - timedelta(minutes=2),
            expires_at=datetime.utcnow() + timedelta(days=1),
        ))
        db.commit()
        with patch(
            "app.integrations.firebase_client.send_password_action_email",
            side_effect=HTTPException(status_code=422, detail="OPERATION_NOT_ALLOWED"),
        ):
            with pytest.raises(HTTPException) as error:
                resend_user_activation(db, user=user)
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert error.value.status_code == 424
        assert "OPERATION_NOT_ALLOWED" in error.value.detail
        assert invitation.status == "delivery_failed"
        assert invitation.send_attempts == 2
        assert user.auth_status == UserAuthStatus.PROVISIONING_FAILED
    finally:
        db.close(); engine.dispose()
