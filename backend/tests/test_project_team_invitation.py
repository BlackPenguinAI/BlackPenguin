from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from app.db.base import Base
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.project_team.router import invite_and_assign_sales_user, list_sales_candidates, upsert_assignment
from app.modules.project_team.schemas import AssignmentUpsert, SalesUserInviteAndAssign
from app.modules.project_team.service import eligible_sales_assignments
from app.modules.projects.models import Project
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.users.models import User, UserAuthStatus, UserRole


def test_sales_invitation_flushes_assignment_when_autoflush_is_disabled(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    try:
        plan = SubscriptionPlan(name="Sales Invite Test", max_sales_users=3, is_active=True)
        company = Company(name="Invite Company", plan=plan, is_active=True)
        db.add_all([plan, company]); db.flush()
        administrator = User(
            company_id=company.id, email="admin@invite.example", first_name="Admin",
            last_name="User", role=UserRole.ADMIN, hashed_password="unused",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        project = Project(company_id=company.id, name="Invite Project", is_active=True)
        db.add_all([administrator, project]); db.commit()
        db.refresh(administrator); db.refresh(project)
        monkeypatch.setattr(
            "app.modules.project_team.router.user_services.provision_invitation",
            lambda *args, **kwargs: SimpleNamespace(id="invitation-1", status="accepted_by_provider"),
        )

        result = invite_and_assign_sales_user(
            project.id,
            SalesUserInviteAndAssign(
                first_name="Sales", last_name="Agent", email="Sales.Agent@Example.com",
            ),
            db,
            administrator,
        )

        invited = db.query(User).filter_by(email="sales.agent@example.com").one()
        assignment = db.query(ProjectUserAssignment).filter_by(
            project_id=project.id, user_id=invited.id,
        ).one()
        assert result["id"] == assignment.id
        assert result["responsibility"] == "sales"
        assert assignment.is_active is True
        assert assignment.accepts_new_leads is True
        assert result["invitation_id"] == "invitation-1"
        assert result["delivery_status"] == "accepted"
    finally:
        db.close(); engine.dispose()


def test_company_administrator_can_be_assigned_as_project_sales_without_an_extra_user():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        company = Company(name="Administrator Sales Company", is_active=True)
        other_company = Company(name="Other Company", is_active=True)
        db.add_all([company, other_company]); db.flush()
        administrator = User(
            company_id=company.id, email="admin@sales.example", first_name="Company",
            last_name="Administrator", role=UserRole.ADMIN, hashed_password="unused",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        other_administrator = User(
            company_id=other_company.id, email="other@sales.example", role=UserRole.ADMIN,
            hashed_password="unused", auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        project = Project(company_id=company.id, name="E2E Project", is_active=True)
        db.add_all([administrator, other_administrator, project]); db.commit()

        candidates = list_sales_candidates(project.id, db, administrator)
        assert [item.id for item in candidates] == [administrator.id]

        assignment = upsert_assignment(
            project.id,
            administrator.id,
            AssignmentUpsert(
                user_id=administrator.id, responsibility="sales", is_primary=True,
                accepts_new_leads=True, is_active=True,
            ),
            db,
            administrator,
        )
        assert assignment["user_id"] == administrator.id
        assert assignment["responsibility"] == "sales"
        assert [item.user_id for item in eligible_sales_assignments(db, project.id)] == [administrator.id]

        with pytest.raises(HTTPException) as denied:
            upsert_assignment(
                project.id,
                other_administrator.id,
                AssignmentUpsert(user_id=other_administrator.id, responsibility="sales"),
                db,
                administrator,
            )
        assert denied.value.status_code == 422
    finally:
        db.close(); engine.dispose()
