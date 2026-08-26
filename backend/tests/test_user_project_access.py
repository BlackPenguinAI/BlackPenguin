import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.base  # noqa: F401 - register every model
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project
from app.modules.users.models import User, UserProjectAccess, UserRole
from app.modules.users.project_access import (
    project_ids_for_user, sync_all_scope_users_for_project, sync_user_project_access,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_all_scope_creates_operational_assignments_and_includes_future_projects():
    _, db = _db()
    company = Company(name="Tenant", is_active=True)
    db.add(company); db.flush()
    first = Project(company_id=company.id, name="First", is_active=True)
    second = Project(company_id=company.id, name="Second", is_active=True)
    user = User(company_id=company.id, email="sales@example.test", hashed_password="x", role=UserRole.SALES)
    db.add_all([first, second, user]); db.flush()

    sync_user_project_access(db, user=user, scope="all", project_ids=[])
    db.commit()
    assert set(project_ids_for_user(db, user)) == {first.id, second.id}
    assert {row.project_id for row in db.query(ProjectUserAssignment).filter_by(user_id=user.id)} == {first.id, second.id}

    future = Project(company_id=company.id, name="Future", is_active=True)
    db.add(future); db.flush()
    sync_all_scope_users_for_project(db, future); db.commit()
    assert db.query(ProjectUserAssignment).filter_by(user_id=user.id, project_id=future.id, is_active=True).one()


def test_selected_scope_is_validated_and_does_not_assign_other_company_projects():
    _, db = _db()
    company = Company(name="Tenant", is_active=True)
    other = Company(name="Other", is_active=True)
    db.add_all([company, other]); db.flush()
    selected = Project(company_id=company.id, name="Selected", is_active=True)
    excluded = Project(company_id=company.id, name="Excluded", is_active=True)
    foreign = Project(company_id=other.id, name="Foreign", is_active=True)
    user = User(company_id=company.id, email="mkt@example.test", hashed_password="x", role=UserRole.MKT)
    db.add_all([selected, excluded, foreign, user]); db.flush()

    sync_user_project_access(db, user=user, scope="selected", project_ids=[selected.id]); db.commit()
    assert project_ids_for_user(db, user) == [selected.id]
    assert db.query(ProjectUserAssignment).filter_by(user_id=user.id, project_id=selected.id, is_active=True).one()
    assert not db.query(ProjectUserAssignment).filter_by(user_id=user.id, project_id=excluded.id).first()
    with pytest.raises(HTTPException) as error:
        sync_user_project_access(db, user=user, scope="selected", project_ids=[foreign.id])
    assert error.value.status_code == 422


def test_migration_auto_assigns_only_unambiguous_legacy_users(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260826_user_project_access.py"
    spec = importlib.util.spec_from_file_location("user_project_access_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine, db = _db()
    one = Company(name="One", is_active=True); many = Company(name="Many", is_active=True)
    db.add_all([one, many]); db.flush()
    only = Project(company_id=one.id, name="Only", is_active=True)
    db.add_all([only, Project(company_id=many.id, name="A", is_active=True), Project(company_id=many.id, name="B", is_active=True)])
    unambiguous = User(company_id=one.id, email="one@example.test", hashed_password="x", role=UserRole.SALES)
    ambiguous = User(company_id=many.id, email="many@example.test", hashed_password="x", role=UserRole.SALES)
    db.add_all([unambiguous, ambiguous]); db.commit()

    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    db.expire_all()
    assert db.query(UserProjectAccess).filter_by(user_id=unambiguous.id, project_id=only.id, is_active=True).one()
    assert db.query(ProjectUserAssignment).filter_by(user_id=unambiguous.id, project_id=only.id, is_active=True).one()
    assert db.query(UserProjectAccess).filter_by(user_id=ambiguous.id).count() == 0
    assert db.get(User, ambiguous.id).project_access_scope == "selected"
