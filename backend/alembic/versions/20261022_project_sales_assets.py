"""Approve, share and audit Project sales materials.

Revision ID: 20261022_sales_assets
Revises: 20261021_shared_profiles
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022_sales_assets"
down_revision = "20261021_shared_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_sales_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_type_id", sa.String(36), sa.ForeignKey("project_property_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("project_onboarding_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False, server_default="other"),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("allowed_channels", sa.JSON(), nullable=False, server_default='["sms", "whatsapp"]'),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "source_id", name="uq_project_sales_asset_source"),
    )
    for column in ("company_id", "project_id", "property_type_id", "source_id", "asset_type", "approval_status", "valid_until"):
        op.create_index(f"ix_project_sales_assets_{column}", "project_sales_assets", [column])

    share_columns = (
        sa.Column("sales_asset_id", sa.String(36), sa.ForeignKey("project_sales_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("outbound_message_id", sa.String(36), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(30), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    for column in share_columns:
        op.add_column("sales_asset_shares", column)
    for column in ("sales_asset_id", "outbound_message_id", "agent_run_id", "channel"):
        op.create_index(f"ix_sales_asset_shares_{column}", "sales_asset_shares", [column])

    op.drop_constraint("sales_asset_access_events_share_id_fkey", "sales_asset_access_events", type_="foreignkey")
    op.alter_column("sales_asset_access_events", "share_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("sales_asset_access_events", "event_type", existing_type=sa.String(20), type_=sa.String(30))
    event_columns = (
        sa.Column("company_id", sa.String(36), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("lead_id", sa.String(36), nullable=True),
        sa.Column("sales_asset_id", sa.String(36), nullable=True),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("outbound_message_id", sa.String(36), nullable=True),
        sa.Column("channel", sa.String(30), nullable=True),
        sa.Column("asset_type", sa.String(40), nullable=True),
        sa.Column("asset_name", sa.String(255), nullable=True),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=True),
    )
    for column in event_columns:
        op.add_column("sales_asset_access_events", column)
    op.execute(
        "UPDATE sales_asset_access_events e SET "
        "company_id=s.company_id, project_id=s.project_id, lead_id=s.lead_id, "
        "source_id=s.source_id, outbound_message_id=s.outbound_message_id, channel=s.channel "
        "FROM sales_asset_shares s WHERE e.share_id=s.id"
    )
    op.execute(
        "UPDATE sales_asset_access_events SET event_hash = "
        "md5(id || ':' || created_at::text) || md5(created_at::text || ':' || id) "
        "WHERE event_hash IS NULL"
    )
    op.alter_column("sales_asset_access_events", "event_hash", existing_type=sa.String(64), nullable=False)
    for column in ("company_id", "project_id", "lead_id", "sales_asset_id", "source_id", "outbound_message_id", "channel", "asset_type"):
        op.create_index(f"ix_sales_asset_access_events_{column}", "sales_asset_access_events", [column])
    op.create_index("ix_sales_asset_access_events_event_hash", "sales_asset_access_events", ["event_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sales_asset_access_events_event_hash", table_name="sales_asset_access_events")
    for column in ("asset_type", "channel", "outbound_message_id", "source_id", "sales_asset_id", "lead_id", "project_id", "company_id"):
        op.drop_index(f"ix_sales_asset_access_events_{column}", table_name="sales_asset_access_events")
    for column in ("event_hash", "previous_hash", "asset_name", "asset_type", "channel", "outbound_message_id", "source_id", "sales_asset_id", "lead_id", "project_id", "company_id"):
        op.drop_column("sales_asset_access_events", column)
    op.alter_column("sales_asset_access_events", "event_type", existing_type=sa.String(30), type_=sa.String(20))
    op.alter_column("sales_asset_access_events", "share_id", existing_type=sa.String(36), nullable=False)
    op.create_foreign_key(
        "sales_asset_access_events_share_id_fkey", "sales_asset_access_events",
        "sales_asset_shares", ["share_id"], ["id"], ondelete="CASCADE",
    )
    for column in ("channel", "agent_run_id", "outbound_message_id", "sales_asset_id"):
        op.drop_index(f"ix_sales_asset_shares_{column}", table_name="sales_asset_shares")
    for column in ("revoked_by_user_id", "revoked_at", "channel", "agent_run_id", "outbound_message_id", "sales_asset_id"):
        op.drop_column("sales_asset_shares", column)
    for column in ("valid_until", "approval_status", "asset_type", "source_id", "property_type_id", "project_id", "company_id"):
        op.drop_index(f"ix_project_sales_assets_{column}", table_name="project_sales_assets")
    op.drop_table("project_sales_assets")
