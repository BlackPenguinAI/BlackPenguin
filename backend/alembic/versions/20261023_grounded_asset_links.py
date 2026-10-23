"""Persist extracted document links and tracked external share targets.

Revision ID: 20261023_grounded_links
Revises: 20261023_asset_consent
"""

from alembic import op
import sqlalchemy as sa


revision = "20261023_grounded_links"
down_revision = "20261023_asset_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_onboarding_sources",
        sa.Column("extracted_links", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column("sales_asset_shares", sa.Column("target_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sales_asset_shares", "target_url")
    op.drop_column("project_onboarding_sources", "extracted_links")
