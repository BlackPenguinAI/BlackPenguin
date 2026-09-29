"""Add Company country and Telnyx WhatsApp configuration.

Revision ID: 20260929_company_whatsapp
Revises: 20260928_telnyx_caps
"""

from alembic import op
import sqlalchemy as sa


revision = "20260929_company_whatsapp"
down_revision = "20260928_telnyx_caps"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    company_columns = _columns("companies")
    with op.batch_alter_table("companies") as batch:
        if "country_code" not in company_columns:
            batch.add_column(sa.Column("country_code", sa.String(2), nullable=True))
            batch.create_index("ix_companies_country_code", ["country_code"], unique=False)

    columns = _columns("telnyx_company_configurations")
    additions = (
        ("primary_channel", sa.String(20), False, "sms"),
        ("whatsapp_business_account_id", sa.String(120), True, None),
        ("whatsapp_phone_number_id", sa.String(120), True, None),
        ("whatsapp_from_phone_number", sa.String(50), True, None),
        ("whatsapp_template_name", sa.String(180), True, None),
        ("whatsapp_template_language", sa.String(20), False, "es"),
        ("live_whatsapp_enabled", sa.Boolean(), False, False),
        ("whatsapp_verification_status", sa.String(30), False, "not_configured"),
        ("whatsapp_verified_at", sa.DateTime(), True, None),
        ("whatsapp_last_error", sa.Text(), True, None),
    )
    with op.batch_alter_table("telnyx_company_configurations") as batch:
        for name, type_, nullable, default in additions:
            if name not in columns:
                batch.add_column(sa.Column(name, type_, nullable=nullable, server_default=(sa.text("true") if default is True else sa.text("false") if default is False else default)))
        if "whatsapp_phone_number_id" not in columns:
            batch.create_unique_constraint("uq_telnyx_company_whatsapp_phone_id", ["whatsapp_phone_number_id"])
        if "whatsapp_from_phone_number" not in columns:
            batch.create_unique_constraint("uq_telnyx_company_whatsapp_number", ["whatsapp_from_phone_number"])


def downgrade() -> None:
    columns = _columns("telnyx_company_configurations")
    with op.batch_alter_table("telnyx_company_configurations") as batch:
        if "whatsapp_from_phone_number" in columns:
            batch.drop_constraint("uq_telnyx_company_whatsapp_number", type_="unique")
        if "whatsapp_phone_number_id" in columns:
            batch.drop_constraint("uq_telnyx_company_whatsapp_phone_id", type_="unique")
        for name in (
            "whatsapp_last_error", "whatsapp_verified_at", "whatsapp_verification_status",
            "live_whatsapp_enabled", "whatsapp_template_language", "whatsapp_template_name",
            "whatsapp_from_phone_number", "whatsapp_phone_number_id",
            "whatsapp_business_account_id", "primary_channel",
        ):
            if name in columns:
                batch.drop_column(name)
    if "country_code" in _columns("companies"):
        with op.batch_alter_table("companies") as batch:
            batch.drop_index("ix_companies_country_code")
            batch.drop_column("country_code")
