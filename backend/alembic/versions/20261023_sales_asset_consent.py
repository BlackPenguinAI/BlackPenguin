"""Persist lead consent state before sharing Project materials.

Revision ID: 20261023_asset_consent
Revises: 20261023_source_intent
"""

from alembic import op
import sqlalchemy as sa


revision = "20261023_asset_consent"
down_revision = "20261023_source_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_onboarding_sources", sa.Column("intended_content_tags", sa.JSON(), nullable=True))
    op.add_column("project_sales_assets", sa.Column("content_tags", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("sales_conversations", sa.Column("pending_asset_id", sa.String(36), nullable=True))
    op.add_column("sales_conversations", sa.Column("pending_asset_offered_at", sa.DateTime(), nullable=True))
    op.create_index("ix_sales_conversations_pending_asset_id", "sales_conversations", ["pending_asset_id"])
    op.create_foreign_key(
        "sales_conversations_pending_asset_id_fkey",
        "sales_conversations", "project_sales_assets",
        ["pending_asset_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("sales_conversations_pending_asset_id_fkey", "sales_conversations", type_="foreignkey")
    op.drop_index("ix_sales_conversations_pending_asset_id", table_name="sales_conversations")
    op.drop_column("sales_conversations", "pending_asset_offered_at")
    op.drop_column("sales_conversations", "pending_asset_id")
    op.drop_column("project_sales_assets", "content_tags")
    op.drop_column("project_onboarding_sources", "intended_content_tags")
