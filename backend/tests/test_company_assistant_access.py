from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.postgres import Base
from app.modules.auth.deps import RoleChecker
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserProjectAccess, UserRole
from app.core.security import verify_password
from app.modules.users.services import create_tenant_user, enforce_role_limit, invite_tenant_user


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SubscriptionPlan.__table__,
            Company.__table__,
            User.__table__,
            Project.__table__,
            UserProjectAccess.__table__,
            ProjectUserAssignment.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _company(db, *, max_assistants=1):
    plan = SubscriptionPlan(
        name="Test",
        max_assistants=max_assistants,
        max_mkt_users=1,
        max_sales_users=1,
    )
    company = Company(name="Tenant", plan=plan, is_active=True)
    db.add_all([plan, company])
    db.commit()
    db.refresh(company)
    return company


def test_assistant_is_a_tenant_manager():
    user = SimpleNamespace(role=UserRole.ASSISTANT)
    assert RoleChecker(TENANT_MANAGER_ROLES)(user) is user


def test_shared_invitation_service_creates_assistant_and_normalizes_email(db):
    company = _company(db)
    with patch("app.modules.users.services.send_user_activation"):
        user = invite_tenant_user(
            db,
            company_id=company.id,
            email=" Assistant@Example.com ",
            first_name=" Ada ",
            last_name=" Lovelace ",
            role=UserRole.ASSISTANT,
        )
    assert user.email == "assistant@example.com"
    assert user.first_name == "Ada"
    assert user.role == UserRole.ASSISTANT


def test_company_manager_can_create_sales_user_with_password_and_status(db):
    company = _company(db)
    user = create_tenant_user(
        db,
        company_id=company.id,
        email=" Sales@Example.com ",
        first_name=" Sam ",
        last_name=" Seller ",
        role=UserRole.SALES,
        password="1234",
        is_active=True,
    )
    assert user.company_id == company.id
    assert user.email == "sales@example.com"
    assert verify_password("1234", user.hashed_password)
    assert user.hashed_password != "1234"


def test_administrator_cannot_be_created_by_tenant_invitation(db):
    company = _company(db)
    with pytest.raises(HTTPException) as error:
        invite_tenant_user(
            db,
            company_id=company.id,
            email="admin2@example.com",
            first_name="Second",
            last_name="Admin",
            role=UserRole.ADMIN,
        )
    assert error.value.status_code == 403


def test_assistant_limit_counts_only_active_seats(db):
    company = _company(db, max_assistants=1)
    db.add(User(
        company_id=company.id,
        email="active@example.com",
        first_name="Active",
        last_name="Assistant",
        role=UserRole.ASSISTANT,
        hashed_password="not-used",
        is_active=True,
    ))
    db.commit()
    with pytest.raises(HTTPException) as error:
        enforce_role_limit(db, company, UserRole.ASSISTANT)
    assert error.value.status_code == 409

    db.query(User).filter(User.email == "active@example.com").update({"is_active": False})
    db.commit()
    enforce_role_limit(db, company, UserRole.ASSISTANT)
