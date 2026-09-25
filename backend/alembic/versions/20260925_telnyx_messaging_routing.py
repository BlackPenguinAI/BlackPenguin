"""Telnyx provider and provider-pinned SMS conversations.

Revision ID: 20260925_telnyx_routing
Revises: 20260917_visit_firestore
"""

from alembic import op
import sqlalchemy as sa


revision = "20260925_telnyx_routing"
down_revision = "20260917_visit_firestore"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "telnyx_configurations" not in tables:
        op.create_table(
            "telnyx_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
            sa.Column("api_key_hint", sa.String(12), nullable=True),
            sa.Column("messaging_profile_id", sa.String(100), nullable=True),
            sa.Column("from_phone_number", sa.String(50), nullable=True),
            sa.Column("webhook_public_key", sa.Text(), nullable=True),
            sa.Column("live_sms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "messaging_routing_configurations" not in tables:
        op.create_table(
            "messaging_routing_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("default_provider", sa.String(20), nullable=False, server_default="twilio"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "provider" not in _columns("sales_conversations"):
        op.add_column("sales_conversations", sa.Column("provider", sa.String(20), nullable=False, server_default="twilio"))
        op.create_index("ix_sales_conversations_provider", "sales_conversations", ["provider"])
    if "provider" not in _columns("outbound_messages"):
        op.add_column("outbound_messages", sa.Column("provider", sa.String(20), nullable=False, server_default="twilio"))
        op.create_index("ix_outbound_messages_provider", "outbound_messages", ["provider"])


def downgrade() -> None:
    if "provider" in _columns("outbound_messages"):
        op.drop_index("ix_outbound_messages_provider", table_name="outbound_messages")
        op.drop_column("outbound_messages", "provider")
    if "provider" in _columns("sales_conversations"):
        op.drop_index("ix_sales_conversations_provider", table_name="sales_conversations")
        op.drop_column("sales_conversations", "provider")
    tables = _tables()
    if "messaging_routing_configurations" in tables:
        op.drop_table("messaging_routing_configurations")
    if "telnyx_configurations" in tables:
        op.drop_table("telnyx_configurations")
