from unittest.mock import patch
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.core.config import settings
from app.integrations import firebase_admin_client
from app.modules.companies.models import Company
from app.modules.companies.services import delete_company_workspace
from app.modules.company_onboarding import services as onboarding_services
from app.modules.company_onboarding.completion import FIELD_BY_KEY
from app.modules.company_onboarding.models import SenderType
from app.modules.company_onboarding.router import _state_payload
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.system_settings.models import FirebaseConfig
from app.modules.users.models import User, UserAuthStatus, UserInvitation, UserRole
from app.modules.users.router import revoke_company_user_invitation


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _company(db):
    plan = SubscriptionPlan(
        name="Deletion Test", max_projects=3, max_assistants=3,
        max_mkt_users=3, max_sales_users=3, is_active=True,
    )
    company = Company(name="Delete Me", plan=plan, is_active=True)
    db.add_all([plan, company]); db.commit(); db.refresh(company)
    return company


def _user(db, company, email, role, uid=None, status=UserAuthStatus.ACTIVE):
    user = User(
        company_id=company.id, email=email, first_name="Test", last_name="User",
        role=role, hashed_password="unused", firebase_uid=uid,
        auth_status=status, is_active=True,
    )
    db.add(user); db.commit(); db.refresh(user)
    return user


def test_company_deletion_removes_remote_identities_before_local_users():
    engine, db = _db()
    try:
        company = _company(db)
        _user(db, company, "admin@example.com", UserRole.ADMIN, "firebase-admin")
        pending = _user(
            db, company, "pending@example.com", UserRole.SALES,
            status=UserAuthStatus.INVITED,
        )
        db.add(UserInvitation(user_id=pending.id, status="accepted_by_provider", expires_at=onboarding_services.datetime.utcnow()))
        db.add(FirebaseConfig(project_id="bp-test", auth_mode="rest")); db.commit()

        with patch("app.integrations.firebase_admin_client.ensure_admin_deletion_ready"), patch(
            "app.integrations.firebase_admin_client.delete_identity", return_value="deleted",
        ) as delete_identity:
            deleted = delete_company_workspace(db, company)

        assert deleted == 2
        assert sorted(
            (call.kwargs for call in delete_identity.call_args_list),
            key=lambda item: item["email"],
        ) == [
            {"project_id": "bp-test", "firebase_uid": "firebase-admin", "email": "admin@example.com"},
            {"project_id": "bp-test", "firebase_uid": None, "email": "pending@example.com"},
        ]
        assert db.query(Company).filter_by(id=company.id).first() is None
        assert db.query(User).filter(User.company_id == company.id).count() == 0
        assert db.query(UserInvitation).count() == 0
    finally:
        db.close(); engine.dispose()


def test_company_deletion_without_bridge_requires_explicit_manual_confirmation(monkeypatch):
    engine, db = _db()
    try:
        company = _company(db)
        user = _user(db, company, "admin@example.com", UserRole.ADMIN, "already-removed-uid")
        db.add(FirebaseConfig(project_id="bp-test", auth_mode="rest")); db.commit()
        monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_URL", "")
        monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_SECRET", "")

        with pytest.raises(HTTPException) as error:
            delete_company_workspace(db, company)

        assert error.value.status_code == 409
        assert error.value.detail == {
            "code": "FIREBASE_ADMIN_DELETE_UNAVAILABLE",
            "message": (
                "Firebase administrative deletion is not configured. "
                "Configure the keyless Firebase Admin bridge, or confirm that the "
                "Company identities were already removed manually from Firebase."
            ),
            "can_confirm_manual_cleanup": True,
        }
        db.expire_all()
        assert db.query(Company).filter_by(id=company.id).one().is_active is True
        assert db.query(User).filter_by(id=user.id).one().is_active is True
    finally:
        db.close(); engine.dispose()


def test_confirmed_manual_firebase_cleanup_completes_local_cascade():
    engine, db = _db()
    try:
        company = _company(db)
        user = _user(db, company, "admin@example.com", UserRole.ADMIN, "already-removed-uid")
        db.add(UserInvitation(
            user_id=user.id,
            status="accepted_by_provider",
            expires_at=onboarding_services.datetime.utcnow(),
        )); db.commit()

        with patch("app.integrations.firebase_admin_client.delete_identity") as delete_identity:
            deleted = delete_company_workspace(
                db,
                company,
                confirm_manual_firebase_cleanup=True,
                deleted_by_user_id="superadmin-1",
            )

        assert deleted == 1
        delete_identity.assert_not_called()
        assert db.query(Company).filter_by(id=company.id).first() is None
        assert db.query(User).filter_by(id=user.id).first() is None
        assert db.query(UserInvitation).filter_by(user_id=user.id).first() is None
    finally:
        db.close(); engine.dispose()


def test_company_deletion_accepts_remote_identity_already_missing():
    engine, db = _db()
    try:
        company = _company(db)
        _user(db, company, "admin@example.com", UserRole.ADMIN, "missing-uid")
        db.add(FirebaseConfig(project_id="bp-test", auth_mode="rest")); db.commit()

        with patch("app.integrations.firebase_admin_client.ensure_admin_deletion_ready"), patch(
            "app.integrations.firebase_admin_client.delete_identity", return_value="not_found",
        ):
            deleted = delete_company_workspace(db, company)

        assert deleted == 1
        assert db.query(Company).filter_by(id=company.id).first() is None
    finally:
        db.close(); engine.dispose()


def test_firebase_admin_bridge_request_is_signed_and_contains_no_private_key(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_URL", "https://firebase-admin.example")
    monkeypatch.setattr(settings, "FIREBASE_ADMIN_BRIDGE_SECRET", "bridge-secret")
    monkeypatch.setattr(firebase_admin_client.time, "time", lambda: 1_700_000_000)

    with patch(
        "app.integrations.firebase_admin_client.httpx.post",
        return_value=type("Response", (), {
            "is_error": False,
            "status_code": 200,
            "json": lambda self: {"status": "not_found"},
        })(),
    ) as request:
        result = firebase_admin_client.delete_identity(
            project_id="bp-test", firebase_uid=None, email="User@Example.com",
        )

    body = request.call_args.kwargs["content"]
    timestamp = request.call_args.kwargs["headers"]["X-BlackPenguin-Timestamp"]
    expected = hmac.new(
        b"bridge-secret", timestamp.encode("ascii") + b"." + body, hashlib.sha256,
    ).hexdigest()
    assert result == "not_found"
    assert request.call_args.args[0] == "https://firebase-admin.example/users/delete"
    assert request.call_args.kwargs["headers"]["X-BlackPenguin-Signature"] == expected
    assert json.loads(body) == {"project_id": "bp-test", "uid": None, "email": "user@example.com"}
    assert b"private_key" not in body


def test_company_deletion_failure_keeps_identifiers_and_disables_access():
    engine, db = _db()
    try:
        company = _company(db)
        user = _user(db, company, "admin@example.com", UserRole.ADMIN, "firebase-admin")
        db.add(FirebaseConfig(project_id="bp-test", auth_mode="rest")); db.commit()
        failure = HTTPException(status_code=502, detail="bridge unavailable")

        with patch("app.integrations.firebase_admin_client.ensure_admin_deletion_ready"), patch(
            "app.integrations.firebase_admin_client.delete_identity", side_effect=failure,
        ):
            with pytest.raises(HTTPException) as error:
                delete_company_workspace(db, company)

        assert error.value.status_code == 502
        db.expire_all()
        saved_company = db.query(Company).filter_by(id=company.id).one()
        saved_user = db.query(User).filter_by(id=user.id).one()
        assert saved_company.is_active is False
        assert saved_user.is_active is False
        assert saved_user.auth_status == UserAuthStatus.SUSPENDED
        assert saved_user.firebase_uid == "firebase-admin"
    finally:
        db.close(); engine.dispose()


def test_failed_invitation_does_not_count_as_an_active_team_role():
    engine, db = _db()
    try:
        company = _company(db)
        user = _user(
            db, company, "failed@example.com", UserRole.SALES,
            status=UserAuthStatus.PROVISIONING_FAILED,
        )
        db.add(UserInvitation(
            user_id=user.id, status="delivery_failed",
            last_error="TOO_MANY_ATTEMPTS_TRY_LATER",
            expires_at=onboarding_services.datetime.utcnow(),
        )); db.commit()

        team = onboarding_services.serialize_team(db, company.id)
        sales = next(item for item in team["roles"] if item["role"] == "sales")
        member = next(item for item in team["members"] if item["id"] == user.id)

        assert sales["active_users"] == 0
        assert sales["pending_users"] == 0
        assert sales["failed_users"] == 1
        assert sales["status"] == "missing"
        assert member["invitation_error_code"] == "TOO_MANY_ATTEMPTS_TRY_LATER"
    finally:
        db.close(); engine.dispose()


def test_revoking_pending_invitation_releases_email_for_reinvitation():
    engine, db = _db()
    try:
        company = _company(db)
        admin = _user(db, company, "admin@example.com", UserRole.ADMIN)
        pending = _user(
            db, company, "reuse@example.com", UserRole.SALES,
            status=UserAuthStatus.PROVISIONING_FAILED,
        )
        db.add(UserInvitation(
            user_id=pending.id, status="delivery_failed", expires_at=onboarding_services.datetime.utcnow(),
        )); db.commit()

        response = revoke_company_user_invitation(pending.id, db, admin)

        assert response["detail"] == "Invitation revoked and pending user removed."
        assert db.query(User).filter_by(email="reuse@example.com").first() is None
        assert db.query(UserInvitation).filter_by(user_id=pending.id).first() is None
    finally:
        db.close(); engine.dispose()


def test_team_transition_creates_a_new_coherent_question_once():
    engine, db = _db()
    try:
        company = _company(db)
        _user(db, company, "admin@example.com", UserRole.ADMIN)
        profile = onboarding_services.get_or_create_profile(db, company.id)
        states = {
            definition.key: {"status": "confirmed", "applicable": True}
            for definition in FIELD_BY_KEY.values()
            if definition.requirement == "required"
        }
        states["company_logo"] = {"status": "deferred", "applicable": True}
        for state_key in onboarding_services.TEAM_ROLE_STATE_KEYS.values():
            states[state_key] = {"status": "deferred", "applicable": True}
        profile.field_states = states
        db.add(profile); db.commit()
        session = onboarding_services.get_or_create_session(db, company.id)
        transition = onboarding_services.save_message(
            db, session.id, SenderType.AI,
            "The required Company Profile is complete. Add Company users now.",
        )

        first = _state_payload(db, company.id)
        second = _state_payload(db, company.id)

        assert first["stage"] == "conditional"
        assert first["next_question"] is not None
        questions = [message for message in second["messages"] if message["ui_payload"]]
        assert len(questions) == 1
        assert questions[0]["content"] == second["next_question"]["prompt"]
        transition_payload = next(message for message in second["messages"] if message["id"] == transition.id)
        assert transition_payload["ui_payload"] is None
    finally:
        db.close(); engine.dispose()
