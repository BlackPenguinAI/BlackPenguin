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
from app.core.security import create_invitation_state, verify_password
from app.db.postgres import Base
from app.modules.auth.router import (
    ChangePasswordPayload,
    CompleteInvitationPayload,
    FirebaseActionCodePayload,
    ForgotPasswordPayload,
    change_password,
    complete_firebase_invitation,
    forgot_password,
    inspect_firebase_action,
)
from app.modules.companies.models import Company
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.system_settings.models import FirebaseConfig
from app.modules.system_settings.schemas import FirebaseConfigUpdate
from app.modules.system_settings.services import firebase_config_response, update_firebase_config
from app.modules.users.models import User, UserAuthStatus, UserInvitation, UserRole
from app.modules.users.services import invite_tenant_user
from app.modules.users.services import invitation_for_idempotency_key
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
        with patch(
            "app.integrations.firebase_client.send_email_sign_in_link"
        ) as send_email:
            user = invite_tenant_user(
                db, company_id=company.id, email="Sales@Northstar.example",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
                timezone="America/New_York", invited_by_user_id=None,
            )
        assert user.auth_status == UserAuthStatus.INVITED
        assert user.firebase_uid is None
        assert user.invitation_sent_at is not None
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert invitation.status == "accepted_by_provider"
        assert invitation.send_attempts == 1
        assert invitation.last_attempt_at is not None
        assert invitation.provisioning_secret_ciphertext is None
        send_email.assert_called_once()
        assert send_email.call_args.args == (db, "sales@northstar.example")
        assert send_email.call_args.kwargs["invitation_state"]
    finally:
        db.close(); engine.dispose()


def test_company_user_invitation_can_be_replayed_with_the_same_idempotency_key():
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        with patch("app.integrations.firebase_client.send_email_sign_in_link") as send_email:
            user = invite_tenant_user(
                db, company_id=company.id, email="replay@example.com",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
                idempotency_key="company-user-request-123",
            )
        replay = invitation_for_idempotency_key(
            db, idempotency_key="company-user-request-123",
            company_id=company.id, email="replay@example.com",
        )
        assert replay is not None
        assert replay.user_id == user.id
        assert db.query(User).filter(User.email == "replay@example.com").count() == 1
        assert db.query(UserInvitation).filter_by(user_id=user.id).count() == 1
        send_email.assert_called_once()
    finally:
        db.close(); engine.dispose()


def test_duplicate_pending_user_returns_an_actionable_conflict():
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        with patch("app.integrations.firebase_client.send_email_sign_in_link"):
            user = invite_tenant_user(
                db, company_id=company.id, email="pending@example.com",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
            )
            with pytest.raises(HTTPException) as error:
                invite_tenant_user(
                    db, company_id=company.id, email="pending@example.com",
                    first_name="Alex", last_name="Rivera", role=UserRole.SALES,
                )
        assert error.value.status_code == 409
        assert error.value.detail == {
            "code": "USER_ALREADY_INVITED",
            "message": "This user is already pending activation.",
            "user_id": user.id,
            "auth_status": "invited",
            "next_action": "resend_activation",
        }
    finally:
        db.close(); engine.dispose()


def test_activation_is_one_time_and_returns_a_tenant_session(caplog):
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="sales@example.com", first_name="Sam",
            last_name="Seller", role=UserRole.SALES, hashed_password="not-used",
            firebase_uid="stale-firebase-sales", auth_status=UserAuthStatus.INVITED,
            is_active=True,
        )
        db.add(user); db.flush()
        invitation = UserInvitation(
            user_id=user.id, status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(invitation)
        db.commit()
        state = create_invitation_state(invitation.id, user.id)
        with caplog.at_level(logging.INFO), patch(
            "app.integrations.firebase_client.sign_in_with_email_link",
            return_value={"localId": "firebase-sales", "idToken": "email-link-id-token"},
        ) as sign_in, patch("app.integrations.firebase_client.update_password") as update_password:
            response = complete_firebase_invitation(
                CompleteInvitationPayload(
                    state=state, oob_code="valid-action-code", new_password="Secure#Pass1",
                ),
                db,
            )
        db.refresh(user)
        invitation = db.query(UserInvitation).filter_by(user_id=user.id).one()
        assert response["role"] == UserRole.SALES
        assert response["access_token"]
        assert user.auth_status == UserAuthStatus.ACTIVE
        assert user.firebase_uid == "firebase-sales"
        assert verify_password("Secure#Pass1", user.hashed_password)
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None
        sign_in.assert_called_once_with(db, email=user.email, oob_code="valid-action-code")
        update_password.assert_called_once_with(
            db, id_token="email-link-id-token", password="Secure#Pass1",
        )
        combined = "\n".join(record.message for record in caplog.records)
        assert f"Firebase email-link activation started company_id={company.id}" in combined
        assert f"user_id={user.id}" in combined
        assert f"invitation_id={invitation.id}" in combined
        assert "Firebase email-link activation completed" in combined
        assert "valid-action-code" not in combined
        assert "Secure#Pass1" not in combined
    finally:
        db.close(); engine.dispose()


def test_invitation_state_cannot_be_tampered_with_or_reused():
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="secure@example.com", first_name="Casey",
            role=UserRole.SALES, hashed_password="not-used",
            auth_status=UserAuthStatus.INVITED, is_active=True,
        )
        db.add(user); db.flush()
        invitation = UserInvitation(
            user_id=user.id, status="accepted_by_provider",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(invitation); db.commit()
        state = create_invitation_state(invitation.id, user.id)

        preview = inspect_firebase_action(FirebaseActionCodePayload(state=state), db)
        assert preview["flow"] == "invitation"
        assert preview["email"] == user.email

        with pytest.raises(HTTPException) as tampered:
            inspect_firebase_action(FirebaseActionCodePayload(state=state + "x"), db)
        assert tampered.value.status_code == 410

        invitation.status = "accepted"
        db.commit()
        with pytest.raises(HTTPException) as reused:
            inspect_firebase_action(FirebaseActionCodePayload(state=state), db)
        assert reused.value.status_code == 410
    finally:
        db.close(); engine.dispose()


def test_expired_invitation_returns_a_specific_safe_reason(caplog):
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="expired@example.com", first_name="Casey",
            role=UserRole.SALES, hashed_password="not-used",
            auth_status=UserAuthStatus.INVITED, is_active=True,
        )
        db.add(user); db.flush()
        invitation = UserInvitation(
            user_id=user.id, status="accepted_by_provider",
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        db.add(invitation); db.commit()
        state = create_invitation_state(invitation.id, user.id)
        with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as error:
            inspect_firebase_action(FirebaseActionCodePayload(state=state), db)
        assert error.value.status_code == 410
        assert error.value.detail["code"] == "INVITATION_EXPIRED"
        assert any("reason=invitation_expired" in record.message for record in caplog.records)
        assert state not in "\n".join(record.message for record in caplog.records)
    finally:
        db.close(); engine.dispose()


def test_successful_resend_revokes_the_previous_email_link():
    engine, db = _db()
    try:
        company = _company(db)
        _verified_firebase(db)
        user = User(
            company_id=company.id, email="renew@example.com", first_name="Riley",
            role=UserRole.SALES, hashed_password="not-used",
            auth_status=UserAuthStatus.INVITED, is_active=True,
        )
        db.add(user); db.flush()
        previous = UserInvitation(
            user_id=user.id, status="accepted_by_provider", send_attempts=1,
            last_attempt_at=datetime.utcnow() - timedelta(minutes=2),
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db.add(previous); db.commit()
        previous_id = previous.id
        with patch("app.integrations.firebase_client.send_email_sign_in_link"):
            current = resend_user_activation(db, user=user)
        db.refresh(previous)
        assert current.id != previous_id
        assert current.status == "accepted_by_provider"
        assert previous.status == "revoked"
        assert previous.revoked_at is not None
    finally:
        db.close(); engine.dispose()


def test_firebase_email_link_and_password_reset_use_distinct_request_types():
    engine, db = _db()
    try:
        _verified_firebase(db)

        class Response:
            is_error = False
            status_code = 200
            def json(self): return {"email": "sales@example.com"}

        with patch("app.integrations.firebase_client.httpx.post", return_value=Response()) as post:
            from app.integrations.firebase_client import send_email_sign_in_link, send_password_reset_email
            send_email_sign_in_link(db, "sales@example.com", invitation_state="signed-state")
            send_password_reset_email(db, "sales@example.com")

        invitation_payload = post.call_args_list[0].kwargs["json"]
        reset_payload = post.call_args_list[1].kwargs["json"]
        assert invitation_payload["requestType"] == "EMAIL_SIGNIN"
        assert invitation_payload["canHandleCodeInApp"] is True
        assert "state=signed-state" in invitation_payload["continueUrl"]
        assert reset_payload["requestType"] == "PASSWORD_RESET"
        assert "passwordReset=complete" in reset_payload["continueUrl"]
        assert "canHandleCodeInApp" not in reset_payload
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
            "app.integrations.firebase_client.send_email_sign_in_link",
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
            and "phase=send_email_sign_in_link" in record.message
            and "error_code=OPERATION_NOT_ALLOWED" in record.message
            for record in caplog.records
        )

        invitation.last_attempt_at = datetime.utcnow() - timedelta(minutes=2)
        db.commit()
        with patch(
            "app.integrations.firebase_client.send_email_sign_in_link",
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


def test_password_recovery_is_separate_from_invitation_activation():
    engine, db = _db()
    try:
        company = _company(db)
        user = User(
            company_id=company.id, email="active@example.com", first_name="Avery",
            role=UserRole.SALES, hashed_password="not-used", firebase_uid="firebase-active",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        db.add(user); db.commit()
        with patch("app.integrations.firebase_client.send_password_reset_email") as send_reset:
            response = forgot_password(ForgotPasswordPayload(email=user.email), db)
        assert response["detail"].startswith("If the account is eligible")
        send_reset.assert_called_once_with(db, user.email)
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
            "app.integrations.firebase_client.send_email_sign_in_link",
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
