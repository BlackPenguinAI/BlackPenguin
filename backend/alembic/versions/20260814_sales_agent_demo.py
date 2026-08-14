"""Add persistent sales-agent conversations and demo execution records.

Revision ID: 20260814_sales_agent_demo
Revises: 20260814_company_catalog_media
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_sales_agent_demo"
down_revision = "20260814_company_catalog_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=True),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False, server_default="new"),
        sa.Column("automation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["project_campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("lead_id", "channel", name="uq_sales_conversation_lead_channel"),
    )
    for column in ("company_id", "project_id", "campaign_id", "lead_id", "stage", "updated_at"):
        op.create_index(f"ix_sales_conversations_{column}", "sales_conversations", [column])

    op.create_table(
        "sales_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(180), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel", "provider_message_id", name="uq_sales_message_provider_id"),
    )
    op.create_index("ix_sales_messages_conversation_id", "sales_messages", ["conversation_id"])
    op.create_index("ix_sales_messages_created_at", "sales_messages", ["created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(180), nullable=False, unique=True),
        sa.Column("mode", sa.String(20), nullable=False, server_default="simulation"),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("graph_version", sa.String(30), nullable=False),
        sa.Column("toolset_version", sa.String(30), nullable=False),
        sa.Column("prompt_configuration_id", sa.String(36), nullable=True),
        sa.Column("prompt_snapshot", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(180), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("output_snapshot", sa.JSON(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("estimated_cost_usd", sa.String(30), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])

    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("agent_run_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(220), nullable=False, unique=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("recipient", sa.String(180), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_outbound_messages_conversation_id", "outbound_messages", ["conversation_id"])
    op.create_index("ix_outbound_messages_agent_run_id", "outbound_messages", ["agent_run_id"])
    op.create_index("ix_outbound_messages_status", "outbound_messages", ["status"])

    op.create_table(
        "external_webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("external_event_id", sa.String(180), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("platform", "external_event_id", name="uq_webhook_platform_event"),
    )
    op.execute(sa.text(
        "INSERT INTO schema_versions (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP) "
        "ON CONFLICT (version) DO NOTHING"
    ).bindparams(version=revision))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision))
    op.drop_table("external_webhook_events")
    op.drop_table("outbound_messages")
    op.drop_table("agent_runs")
    op.drop_table("sales_messages")
    op.drop_table("sales_conversations")
