"""separate project user capabilities for routing and appointments

Revision ID: 20261024_user_capabilities
Revises: 20261023_grounded_links
"""

from __future__ import annotations

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20261024_user_capabilities"
down_revision = "20261023_grounded_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_user_assignments", sa.Column("sales_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("project_user_assignments", sa.Column("marketing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("project_user_assignments", sa.Column("accepts_appointments", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("""
        UPDATE project_user_assignments
        SET sales_enabled = CASE WHEN responsibility = 'sales' THEN TRUE ELSE FALSE END,
            marketing_enabled = CASE WHEN responsibility = 'marketing' THEN TRUE ELSE FALSE END,
            accepts_appointments = CASE WHEN responsibility = 'sales' AND is_active THEN TRUE ELSE FALSE END
    """))
    op.execute(sa.text("""
        UPDATE project_user_assignments AS pua
        SET sales_enabled = TRUE,
            marketing_enabled = TRUE,
            accepts_appointments = CASE WHEN pua.is_active THEN TRUE ELSE FALSE END
        FROM users AS u
        WHERE u.id = pua.user_id
          AND lower(CAST(u.role AS TEXT)) = 'admin'
    """))

    bind = op.get_bind()
    missing = bind.execute(sa.text("""
        SELECT p.id AS project_id, u.id AS user_id
        FROM projects p
        JOIN users u ON u.company_id = p.company_id
        LEFT JOIN project_user_assignments pua
          ON pua.project_id = p.id AND pua.user_id = u.id
        WHERE p.is_active = TRUE
          AND u.is_active = TRUE
          AND lower(CAST(u.role AS TEXT)) = 'admin'
          AND COALESCE(u.project_access_scope, 'all') = 'all'
          AND pua.id IS NULL
    """)).mappings().all()
    assignment_table = sa.table(
        "project_user_assignments",
        sa.column("id", sa.String()), sa.column("project_id", sa.String()),
        sa.column("user_id", sa.String()), sa.column("responsibility", sa.String()),
        sa.column("sales_enabled", sa.Boolean()), sa.column("marketing_enabled", sa.Boolean()),
        sa.column("accepts_appointments", sa.Boolean()), sa.column("is_primary", sa.Boolean()),
        sa.column("routing_weight", sa.Integer()), sa.column("accepts_new_leads", sa.Boolean()),
        sa.column("is_active", sa.Boolean()), sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    if missing:
        now = datetime.utcnow()
        op.bulk_insert(assignment_table, [{
            "id": str(uuid.uuid4()), "project_id": row["project_id"], "user_id": row["user_id"],
            "responsibility": "sales", "sales_enabled": True, "marketing_enabled": True,
            "accepts_appointments": True, "is_primary": False, "routing_weight": 100,
            "accepts_new_leads": True, "is_active": True,
            "created_at": now, "updated_at": now,
        } for row in missing])

    # Safe, location-based repair for legacy Mexico City Projects that were
    # left at the generic UTC default during onboarding.
    op.execute(sa.text("""
        UPDATE projects
        SET timezone = 'America/Mexico_City'
        WHERE timezone = 'UTC'
          AND (
            lower(COALESCE(city, '')) IN ('ciudad de méxico', 'ciudad de mexico', 'mexico city')
            OR lower(COALESCE(address, '')) LIKE '%ciudad de méxico%'
            OR lower(COALESCE(address, '')) LIKE '%ciudad de mexico%'
          )
    """))


def downgrade() -> None:
    op.drop_column("project_user_assignments", "accepts_appointments")
    op.drop_column("project_user_assignments", "marketing_enabled")
    op.drop_column("project_user_assignments", "sales_enabled")
