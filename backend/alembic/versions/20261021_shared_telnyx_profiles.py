"""Allow a Telnyx Messaging Profile to serve multiple Company numbers.

Revision ID: 20261021_shared_profiles
Revises: 20261015_audit_refs
"""

from alembic import op


revision = "20261021_shared_profiles"
down_revision = "20261015_audit_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_telnyx_company_config_profile",
        "telnyx_company_configurations",
        type_="unique",
    )
    op.execute(
        "UPDATE telnyx_company_configurations "
        "SET primary_channel = 'automatic' "
        "WHERE primary_channel IN ('sms', 'whatsapp')"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_telnyx_company_config_profile",
        "telnyx_company_configurations",
        ["messaging_profile_id"],
    )
