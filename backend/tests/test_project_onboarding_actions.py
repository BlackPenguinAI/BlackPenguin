from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.models import (
    Project, ProjectMessage, ProjectProfile, ProjectSession, SenderType,
)
from app.modules.projects.router import apply_onboarding_action
from app.modules.projects.schemas import ProjectOnboardingActionRequest
from app.modules.users.models import User, UserRole


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_ai_sales_authorization_is_atomic_and_idempotent():
    db = _db()
    company = Company(name="Tenant")
    db.add(company); db.flush()
    admin = User(
        company_id=company.id, email="admin@example.com", hashed_password="unused",
        role=UserRole.ADMIN, is_active=True,
    )
    project = Project(company_id=company.id, name="Project")
    db.add_all([admin, project]); db.flush()
    profile = ProjectProfile(project_id=project.id, profile_data={}, field_states={})
    session = ProjectSession(project_id=project.id)
    db.add_all([profile, session]); db.flush()
    question = ProjectMessage(
        session_id=session.id, sender=SenderType.AI,
        content="Authorize AI-assisted sales?",
        ui_payload={
            "field": "sales_authorization", "input_type": "ai_sales_authorization",
            "prompt": "Authorize AI-assisted sales?",
        },
    )
    db.add(question); db.commit()
    action_id = "8e810d1c-b965-4c85-8175-1a31f6f8fb2a"
    payload = ProjectOnboardingActionRequest(
        action="authorize_ai_sales", question_message_id=question.id,
        client_action_id=action_id,
    )

    first = apply_onboarding_action(project.id, payload, Response(), db, admin)
    second = apply_onboarding_action(project.id, payload, Response(), db, admin)

    db.refresh(profile); db.refresh(question)
    assert profile.profile_data["sales_authorization"] is True
    assert profile.field_states["sales_authorization"]["status"] == "confirmed"
    assert question.response_payload["status"] == "accepted"
    assert first["user_message"]["id"] == action_id
    assert second["user_message"]["id"] == action_id
    assert db.query(ProjectMessage).filter(ProjectMessage.id == action_id).count() == 1
