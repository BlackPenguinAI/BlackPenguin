from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
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


def test_invitation_provisions_firebase_without_an_administrator_password():
    engine, db = _db()
    try:
        company = _company(db)
        with patch("app.integrations.firebase_client.create_identity") as create_identity, patch(
            "app.integrations.firebase_client.send_password_action_email"
        ) as send_email:
            create_identity.side_effect = lambda _db, **kwargs: SimpleNamespace(uid=kwargs["uid"])
            user = invite_tenant_user(
                db, company_id=company.id, email="Sales@Northstar.example",
                first_name="Alex", last_name="Rivera", role=UserRole.SALES,
                timezone="America/New_York", invited_by_user_id=None,
            )
        assert user.auth_status == UserAuthStatus.INVITED
        assert user.firebase_uid == user.id
        assert user.invitation_sent_at is not None
        assert db.query(UserInvitation).filter_by(user_id=user.id, status="pending").count() == 1
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
        ), patch("app.integrations.firebase_client.update_identity"):
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


def test_firebase_service_account_is_write_only_and_encrypted():
    engine, db = _db()
    try:
        raw = '{"project_id":"bp-test","client_email":"firebase@bp-test.iam.gserviceaccount.com","private_key":"secret"}'
        config = update_firebase_config(db, FirebaseConfigUpdate(
            project_id="bp-test", api_key="public-api-key",
            auth_domain="bp-test.firebaseapp.com", credentials_json=raw,
            action_handler_url="https://blackpenguin.ai/activate-account",
        ))
        response = firebase_config_response(config)
        assert config.credentials_json is None
        assert config.service_account_ciphertext
        assert raw not in config.service_account_ciphertext
        assert response["credentials_configured"] is True
        assert "credentials_json" not in response
        assert response["credentials_hint"] == "firebase@bp-test.iam.gserviceaccount.com"
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
            auth_mode="firebase", action_handler_url="https://blackpenguin.ai/activate-account",
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
            return_value={"localId": user.firebase_uid},
        ) as sign_in, patch("app.integrations.firebase_client.update_identity") as update_identity:
            response = change_password(
                ChangePasswordPayload(current_password="OldSecure#1", new_password="NewSecure#2"),
                db,
                user,
            )
        assert response["detail"] == "Password updated successfully."
        sign_in.assert_called_once_with(db, user.email, "OldSecure#1")
        update_identity.assert_called_once_with(db, uid=user.firebase_uid, password="NewSecure#2")
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
