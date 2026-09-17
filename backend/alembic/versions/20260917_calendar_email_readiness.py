"""Calendar identity and appointment email outbox.

Revision ID: 20260917_calendar_email
Revises: 20260915_compliance_ops
"""

from alembic import op
import sqlalchemy as sa


revision = "20260917_calendar_email"
down_revision = "20260915_compliance_ops"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "account_email" not in _columns("calendar_connections"):
        op.add_column("calendar_connections", sa.Column("account_email", sa.String(255), nullable=True))
    if "appointment_email_outbox" not in _tables():
        op.create_table(
            "appointment_email_outbox",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("recipient_email", sa.String(255), nullable=False),
            sa.Column("recipient_kind", sa.String(20), nullable=False),
            sa.Column("dedupe_key", sa.String(180), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(120), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("dedupe_key", name="uq_appointment_email_outbox_dedupe"),
        )


def downgrade() -> None:
    if "appointment_email_outbox" in _tables():
        op.drop_table("appointment_email_outbox")
    if "account_email" in _columns("calendar_connections"):
        op.drop_column("calendar_connections", "account_email")
