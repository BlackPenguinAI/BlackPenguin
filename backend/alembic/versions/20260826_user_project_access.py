"""Add non-destructive Company user Project access scopes.

Revision ID: 20260826_user_project_access
Revises: 20260825_schedule_tz
"""

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260826_user_project_access"
down_revision = "20260825_schedule_tz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables or "projects" not in tables:
        return
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "project_access_scope" not in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("project_access_scope", sa.String(20), nullable=False, server_default="all"))
    if "user_project_access" not in tables:
        op.create_table(
            "user_project_access",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "project_id", name="uq_user_project_access"),
        )
        op.create_index("ix_user_project_access_user_id", "user_project_access", ["user_id"])
        op.create_index("ix_user_project_access_project_id", "user_project_access", ["project_id"])

    metadata = sa.MetaData()
    users = sa.Table("users", metadata, autoload_with=bind)
    projects = sa.Table("projects", metadata, autoload_with=bind)
    access = sa.Table("user_project_access", metadata, autoload_with=bind)
    assignments = sa.Table("project_user_assignments", metadata, autoload_with=bind) if "project_user_assignments" in tables else None
    now = datetime.utcnow()
    for user in bind.execute(sa.select(users.c.id, users.c.company_id, users.c.role)).mappings():
        role = str(getattr(user["role"], "value", user["role"])).lower().split(".")[-1]
        if role not in {"sales", "mkt"} or not user["company_id"]:
            continue
        bind.execute(users.update().where(users.c.id == user["id"]).values(project_access_scope="selected"))
        existing_project_ids: list[str] = []
        if assignments is not None:
            existing_project_ids = [
                row[0] for row in bind.execute(sa.select(assignments.c.project_id).where(
                    assignments.c.user_id == user["id"],
                )).all()
            ]
        if not existing_project_ids:
            company_projects = [
                row[0] for row in bind.execute(sa.select(projects.c.id).where(
                    projects.c.company_id == user["company_id"], projects.c.is_active.is_(True),
                )).all()
            ]
            if len(company_projects) == 1:
                existing_project_ids = company_projects
                if assignments is not None:
                    bind.execute(assignments.insert().values(
                        id=str(uuid.uuid4()), project_id=company_projects[0], user_id=user["id"],
                        responsibility="sales" if role == "sales" else "marketing",
                        is_primary=False, routing_weight=100, accepts_new_leads=True,
                        is_active=True, created_at=now, updated_at=now,
                    ))
        for project_id in existing_project_ids:
            exists = bind.execute(sa.select(access.c.id).where(
                access.c.user_id == user["id"], access.c.project_id == project_id,
            )).first()
            if not exists:
                bind.execute(access.insert().values(
                    id=str(uuid.uuid4()), user_id=user["id"], project_id=project_id,
                    is_active=True, created_at=now, updated_at=now,
                ))


def downgrade() -> None:
    # Access and routing choices are business data and are intentionally preserved.
    pass
