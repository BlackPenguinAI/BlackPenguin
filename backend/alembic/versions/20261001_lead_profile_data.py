"""Add a progressive, source-aware lead profile.

Revision ID: 20261001_lead_profile
Revises: 20261001_wa_template_snapshot
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_lead_profile"
down_revision = "20261001_wa_template_snapshot"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "lead_profile_data" not in _columns("leads"):
        with op.batch_alter_table("leads") as batch:
            batch.add_column(sa.Column("lead_profile_data", sa.JSON(), nullable=True))
        op.execute(sa.text("UPDATE leads SET lead_profile_data = '{}' WHERE lead_profile_data IS NULL"))
        with op.batch_alter_table("leads") as batch:
            batch.alter_column("lead_profile_data", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    if "lead_profile_data" in _columns("leads"):
        with op.batch_alter_table("leads") as batch:
            batch.drop_column("lead_profile_data")
