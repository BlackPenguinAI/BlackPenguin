"""Add the authoritative Company timezone and proposal revision history.

Revision ID: 20261014_company_timezone
Revises: 20261001_inbound_jobs
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_company_timezone"
down_revision = "20261001_inbound_jobs"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "timezone" not in _columns("companies"):
        with op.batch_alter_table("companies") as batch:
            batch.add_column(sa.Column("timezone", sa.String(length=80), nullable=False, server_default="UTC"))
    for table in ("company_onboarding_proposals", "project_onboarding_proposals"):
        columns = _columns(table)
        with op.batch_alter_table(table) as batch:
            if "revision" not in columns:
                batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
            if "review_history" not in columns:
                batch.add_column(sa.Column("review_history", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    for table in ("project_onboarding_proposals", "company_onboarding_proposals"):
        columns = _columns(table)
        with op.batch_alter_table(table) as batch:
            if "review_history" in columns:
                batch.drop_column("review_history")
            if "revision" in columns:
                batch.drop_column("revision")
    if "timezone" in _columns("companies"):
        with op.batch_alter_table("companies") as batch:
            batch.drop_column("timezone")
