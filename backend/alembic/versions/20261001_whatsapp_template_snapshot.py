"""Persist the lead-visible WhatsApp template snapshot.

Revision ID: 20261001_wa_template_snapshot
Revises: 20260929_company_whatsapp
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_wa_template_snapshot"
down_revision = "20260929_company_whatsapp"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "whatsapp_template_content" not in _columns("telnyx_company_configurations"):
        with op.batch_alter_table("telnyx_company_configurations") as batch:
            batch.add_column(sa.Column("whatsapp_template_content", sa.Text(), nullable=True))


def downgrade() -> None:
    if "whatsapp_template_content" in _columns("telnyx_company_configurations"):
        with op.batch_alter_table("telnyx_company_configurations") as batch:
            batch.drop_column("whatsapp_template_content")
