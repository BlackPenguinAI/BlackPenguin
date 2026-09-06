from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.project_team.router import invite_and_assign_sales_user
from app.modules.project_team.schemas import SalesUserInviteAndAssign
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
            lambda *args, **kwargs: None,
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
    finally:
        db.close(); engine.dispose()
