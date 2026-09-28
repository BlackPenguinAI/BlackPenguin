"""Persist calculated Telnyx sender-country capabilities.

Revision ID: 20260928_telnyx_caps
Revises: 20260925_telnyx_tenants
"""

from alembic import op
import sqlalchemy as sa


revision = "20260928_telnyx_caps"
down_revision = "20260925_telnyx_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        item["name"] for item in inspector.get_columns("telnyx_company_configurations")
    }
    with op.batch_alter_table("telnyx_company_configurations") as batch:
        if "sender_country_code" not in columns:
            batch.add_column(sa.Column("sender_country_code", sa.String(2), nullable=True))
        if "coverage_snapshot" not in columns:
            batch.add_column(sa.Column("coverage_snapshot", sa.JSON(), nullable=True))
        if "coverage_checked_at" not in columns:
            batch.add_column(sa.Column("coverage_checked_at", sa.DateTime(), nullable=True))
    op.execute(sa.text(
        "UPDATE telnyx_company_configurations SET coverage_snapshot = '{}' "
        "WHERE coverage_snapshot IS NULL"
    ))
    with op.batch_alter_table("telnyx_company_configurations") as batch:
        batch.alter_column(
            "coverage_snapshot", existing_type=sa.JSON(), nullable=False,
        )


def downgrade() -> None:
    columns = {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns(
            "telnyx_company_configurations"
        )
    }
    with op.batch_alter_table("telnyx_company_configurations") as batch:
        for name in ("coverage_checked_at", "coverage_snapshot", "sender_country_code"):
            if name in columns:
                batch.drop_column(name)
