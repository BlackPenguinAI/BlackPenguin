"""Add exact Meta attribution and live-test lead marker.

Revision ID: 20260905_meta_live_sms
Revises: 20260904_invite_reliability
"""

from alembic import op
import sqlalchemy as sa


revision = "20260905_meta_live_sms"
down_revision = "20260904_invite_reliability"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    campaign_columns = _columns("project_campaigns")
    if "external_adset_id" not in campaign_columns:
        op.add_column("project_campaigns", sa.Column("external_adset_id", sa.String(150), nullable=True))
    if "external_ad_id" not in campaign_columns:
        op.add_column("project_campaigns", sa.Column("external_ad_id", sa.String(150), nullable=True))
    if "instagram_account_id" not in _columns("meta_connections"):
        op.add_column("meta_connections", sa.Column("instagram_account_id", sa.String(150), nullable=True))
    if "is_test" not in _columns("leads"):
        op.add_column("leads", sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "ix_leads_is_test" not in _indexes("leads"):
        op.create_index("ix_leads_is_test", "leads", ["is_test"], unique=False)
    if "sales_conversation_lead_contexts" not in _tables():
        op.create_table(
            "sales_conversation_lead_contexts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("activated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("conversation_id", "lead_id", name="uq_sales_conversation_lead_context"),
        )
        op.create_index("ix_sales_conversation_lead_contexts_conversation_id", "sales_conversation_lead_contexts", ["conversation_id"])
        op.create_index("ix_sales_conversation_lead_contexts_lead_id", "sales_conversation_lead_contexts", ["lead_id"])
        op.create_index("ix_sales_conversation_lead_contexts_is_active", "sales_conversation_lead_contexts", ["is_active"])


def downgrade() -> None:
    if "sales_conversation_lead_contexts" in _tables():
        op.drop_table("sales_conversation_lead_contexts")
    if "ix_leads_is_test" in _indexes("leads"):
        op.drop_index("ix_leads_is_test", table_name="leads")
    if "is_test" in _columns("leads"):
        op.drop_column("leads", "is_test")
    if "instagram_account_id" in _columns("meta_connections"):
        op.drop_column("meta_connections", "instagram_account_id")
    campaign_columns = _columns("project_campaigns")
    if "external_ad_id" in campaign_columns:
        op.drop_column("project_campaigns", "external_ad_id")
    if "external_adset_id" in campaign_columns:
        op.drop_column("project_campaigns", "external_adset_id")
