"""Exact appointment locations and Firestore email delivery state.

Revision ID: 20260917_visit_firestore
Revises: 20260917_calendar_email
"""

from alembic import op
import sqlalchemy as sa


revision = "20260917_visit_firestore"
down_revision = "20260917_calendar_email"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    meeting_columns = _columns("meetings")
    for name, column in (
        ("visit_location_label", sa.Column("visit_location_label", sa.String(180), nullable=True)),
        ("visit_address", sa.Column("visit_address", sa.Text(), nullable=True)),
        ("location_confirmation_status", sa.Column("location_confirmation_status", sa.String(30), nullable=False, server_default="required")),
        ("location_confirmed_at", sa.Column("location_confirmed_at", sa.DateTime(), nullable=True)),
        ("location_confirmed_by", sa.Column("location_confirmed_by", sa.String(30), nullable=True)),
    ):
        if name not in meeting_columns:
            op.add_column("meetings", column)

    outbox_columns = _columns("appointment_email_outbox")
    for name, column in (
        ("provider_message_id", sa.Column("provider_message_id", sa.String(255), nullable=True)),
        ("delivery_status", sa.Column("delivery_status", sa.String(30), nullable=True)),
        ("delivered_at", sa.Column("delivered_at", sa.DateTime(), nullable=True)),
    ):
        if name not in outbox_columns:
            op.add_column("appointment_email_outbox", column)

    firebase_columns = _columns("firebase_configurations")
    for name, column in (
        ("appointment_email_enabled", sa.Column("appointment_email_enabled", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("appointment_from_name", sa.Column("appointment_from_name", sa.String(120), nullable=False, server_default="Black Penguin")),
        ("appointment_from_email", sa.Column("appointment_from_email", sa.String(255), nullable=True)),
        ("appointment_reply_to", sa.Column("appointment_reply_to", sa.String(255), nullable=True)),
        ("appointment_mail_collection", sa.Column("appointment_mail_collection", sa.String(120), nullable=False, server_default="mail")),
        ("appointment_transport_status", sa.Column("appointment_transport_status", sa.String(30), nullable=False, server_default="not_configured")),
        ("appointment_transport_error", sa.Column("appointment_transport_error", sa.Text(), nullable=True)),
    ):
        if name not in firebase_columns:
            op.add_column("firebase_configurations", column)


def downgrade() -> None:
    for name in ("appointment_transport_error", "appointment_transport_status", "appointment_mail_collection", "appointment_reply_to", "appointment_from_email", "appointment_from_name", "appointment_email_enabled"):
        if name in _columns("firebase_configurations"):
            op.drop_column("firebase_configurations", name)
    for name in ("delivered_at", "delivery_status", "provider_message_id"):
        if name in _columns("appointment_email_outbox"):
            op.drop_column("appointment_email_outbox", name)
    for name in ("location_confirmed_by", "location_confirmed_at", "location_confirmation_status", "visit_address", "visit_location_label"):
        if name in _columns("meetings"):
            op.drop_column("meetings", name)
