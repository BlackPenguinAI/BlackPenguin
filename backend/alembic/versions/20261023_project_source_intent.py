"""Persist Project file purpose selected during upload.

Revision ID: 20261023_source_intent
Revises: 20261022_sales_assets
"""

from alembic import op
import sqlalchemy as sa


revision = "20261023_source_intent"
down_revision = "20261022_sales_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_onboarding_sources",
        sa.Column("sharing_intent", sa.String(30), nullable=False, server_default="internal"),
    )
    op.add_column("project_onboarding_sources", sa.Column("intended_asset_type", sa.String(40), nullable=True))
    op.add_column("project_onboarding_sources", sa.Column("intended_display_name", sa.String(255), nullable=True))
    op.add_column("project_onboarding_sources", sa.Column("intended_allowed_channels", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_onboarding_sources", "intended_allowed_channels")
    op.drop_column("project_onboarding_sources", "intended_display_name")
    op.drop_column("project_onboarding_sources", "intended_asset_type")
    op.drop_column("project_onboarding_sources", "sharing_intent")
