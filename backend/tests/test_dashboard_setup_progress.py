from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.company_onboarding.completion import CONDITIONAL_FIELDS, REQUIRED_FIELDS
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.dashboard.router import _setup_progress
from app.modules.projects.models import Project, ProjectProfile
from app.modules.sales_crm.models import Lead, SalesAvailabilityBlock
from app.modules.users.models import User, UserRole


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _administrator(db, company):
    user = User(
        company_id=company.id,
        email=f"admin-{company.id}@example.com",
        hashed_password="unused",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user); db.flush()
    return user


def _complete_company_profile(db, company):
    states = {
        field.key: {"status": "confirmed", "applicable": True}
        for field in REQUIRED_FIELDS
    }
    states.update({
        field.key: {"status": "not_applicable", "applicable": False}
        for field in CONDITIONAL_FIELDS
    })
    profile = CompanyProfile(
        company_id=company.id,
        profile_data={"official_company_name": company.name},
        field_states=states,
        final_approved=True,
        completion_percentage=100,
    )
    db.add(profile); db.flush()
    return profile


def _complete_project(db, company, *, demo=False):
    project = Project(
        company_id=company.id,
        name="Demo" if demo else "First Project",
        is_demo=demo,
        is_active=True,
        onboarding_status="completed",
    )
    db.add(project); db.flush()
    db.add(ProjectProfile(project_id=project.id, final_approved=True, completion_percentage=100))
    db.flush()
    return project


def test_setup_progress_advances_only_from_persisted_non_demo_state():
    engine, db = _db()
    try:
        company = Company(name="Tenant")
        db.add(company); db.flush()
        user = _administrator(db, company)

        initial = _setup_progress(db, user)
        assert initial["current_step"] == "company"
        assert [step["status"] for step in initial["steps"]] == [
            "current", "locked", "locked", "locked",
        ]

        _complete_company_profile(db, company)
        _complete_project(db, company, demo=True)
        db.commit()
        after_demo = _setup_progress(db, user)
        assert after_demo["current_step"] == "project"
        assert after_demo["steps"][1]["url"] == "/app/projects"

        project = _complete_project(db, company)
        db.commit()
        after_project = _setup_progress(db, user)
        assert after_project["current_step"] == "availability"
        assert after_project["steps"][2]["entity_id"] == project.id
        assert after_project["next_url"].startswith("/app/schedule")

        db.add(SalesAvailabilityBlock(
            user_id=user.id,
            starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            timezone="America/Lima",
        ))
        db.commit()
        after_availability = _setup_progress(db, user)
        assert after_availability["current_step"] == "lead"
        assert f"project={project.id}" in after_availability["next_url"]

        db.add(Lead(
            company_id=company.id,
            project_id=project.id,
            full_name="Manual Lead",
            phone="+13055550100",
            platform="manual",
            is_demo=False,
        ))
        db.commit()
        complete = _setup_progress(db, user)
        assert complete["current_step"] == "complete"
        assert complete["is_complete"] is True
        assert all(step["status"] == "complete" for step in complete["steps"])
    finally:
        db.close(); engine.dispose()


def test_setup_progress_is_tenant_scoped_and_ignores_expired_availability():
    engine, db = _db()
    try:
        first = Company(name="First")
        second = Company(name="Second")
        db.add_all([first, second]); db.flush()
        first_admin = _administrator(db, first)
        second_admin = _administrator(db, second)
        _complete_company_profile(db, first)
        _complete_company_profile(db, second)
        _complete_project(db, first)
        _complete_project(db, second)
        db.add_all([
            SalesAvailabilityBlock(
                user_id=first_admin.id,
                starts_at=datetime.utcnow() - timedelta(days=2),
                ends_at=datetime.utcnow() - timedelta(days=1),
                timezone="UTC",
            ),
            SalesAvailabilityBlock(
                user_id=second_admin.id,
                starts_at=datetime.utcnow() + timedelta(days=1),
                ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
                timezone="UTC",
            ),
        ])
        db.commit()

        progress = _setup_progress(db, first_admin)
        assert progress["current_step"] == "availability"
        assert progress["steps"][2]["status"] == "current"
    finally:
        db.close(); engine.dispose()
