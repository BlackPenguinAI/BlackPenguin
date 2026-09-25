"""Tenant-isolated Telnyx sender numbers and Messaging Profiles.

Revision ID: 20260925_telnyx_tenants
Revises: 20260925_telnyx_routing
"""

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260925_telnyx_tenants"
down_revision = "20260925_telnyx_routing"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "telnyx_company_configurations" not in tables:
        op.create_table(
            "telnyx_company_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("messaging_profile_id", sa.String(100), nullable=True),
            sa.Column("from_phone_number", sa.String(50), nullable=True),
            sa.Column("telnyx_phone_number_id", sa.String(100), nullable=True),
            sa.Column("regulatory_status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("live_sms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("company_id", name="uq_telnyx_company_config_company"),
            sa.UniqueConstraint("messaging_profile_id", name="uq_telnyx_company_config_profile"),
            sa.UniqueConstraint("from_phone_number", name="uq_telnyx_company_config_number"),
            sa.UniqueConstraint("telnyx_phone_number_id", name="uq_telnyx_company_config_phone_id"),
        )
        op.create_index("ix_telnyx_company_configurations_company_id", "telnyx_company_configurations", ["company_id"])

    # Preserve the first release's sender automatically only when there is one
    # tenant. Multiple tenants require an explicit assignment to avoid leaking a
    # shared physical SMS thread across companies.
    connection = op.get_bind()
    if not {"companies", "telnyx_configurations"}.issubset(_tables()):
        return
    configured = connection.execute(sa.text("SELECT COUNT(*) FROM telnyx_company_configurations")).scalar() or 0
    company_rows = connection.execute(sa.text("SELECT id FROM companies ORDER BY created_at ASC")).fetchall()
    if configured or len(company_rows) != 1:
        return
    legacy = connection.execute(sa.text(
        "SELECT messaging_profile_id, from_phone_number FROM telnyx_configurations "
        "WHERE messaging_profile_id IS NOT NULL AND from_phone_number IS NOT NULL LIMIT 1"
    )).mappings().first()
    if not legacy:
        return
    connection.execute(sa.text(
        "INSERT INTO telnyx_company_configurations "
        "(id, company_id, messaging_profile_id, from_phone_number, regulatory_status, "
        "live_sms_enabled, verification_status, updated_at) "
        "VALUES (:id, :company_id, :profile_id, :phone, :regulatory, :enabled, :verification, :updated_at)"
    ), {
        "id": str(uuid.uuid4()),
        "company_id": company_rows[0][0],
        "profile_id": legacy["messaging_profile_id"],
        "phone": legacy["from_phone_number"],
        "regulatory": "pending",
        "enabled": False,
        "verification": "pending",
        "updated_at": datetime.utcnow(),
    })


def downgrade() -> None:
    if "telnyx_company_configurations" in _tables():
        op.drop_index("ix_telnyx_company_configurations_company_id", table_name="telnyx_company_configurations")
        op.drop_table("telnyx_company_configurations")
