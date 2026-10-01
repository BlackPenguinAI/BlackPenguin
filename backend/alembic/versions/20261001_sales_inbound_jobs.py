"""Add durable inbound Sales Agent jobs.

Revision ID: 20261001_inbound_jobs
Revises: 20261001_lead_profile
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_inbound_jobs"
down_revision = "20261001_lead_profile"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "sales_inbound_jobs" in _tables():
        return
    op.create_table(
        "sales_inbound_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("sales_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", name="uq_sales_inbound_job_message"),
    )
    op.create_index("ix_sales_inbound_jobs_conversation_id", "sales_inbound_jobs", ["conversation_id"])
    op.create_index("ix_sales_inbound_jobs_message_id", "sales_inbound_jobs", ["message_id"])
    op.create_index("ix_sales_inbound_jobs_status", "sales_inbound_jobs", ["status"])
    op.create_index("ix_sales_inbound_jobs_scheduled_at", "sales_inbound_jobs", ["scheduled_at"])


def downgrade() -> None:
    if "sales_inbound_jobs" in _tables():
        op.drop_table("sales_inbound_jobs")
