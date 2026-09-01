"""Expose truthful Company source-processing stages.

Revision ID: 20260903_source_progress
Revises: 20260902_firebase_rest
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_source_progress"
down_revision = "20260902_firebase_rest"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns("company_onboarding_sources")
    if "processing_stage" not in columns:
        op.add_column(
            "company_onboarding_sources",
            sa.Column("processing_stage", sa.String(40), nullable=False, server_default="queued"),
        )
    if "processing_detail" not in columns:
        op.add_column(
            "company_onboarding_sources",
            sa.Column("processing_detail", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    # Non-destructive: operational progress remains useful for audit and support.
    pass
