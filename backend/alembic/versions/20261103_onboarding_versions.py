"""Keep approved profiles available while their next revision is reviewed.

Revision ID: 20261103_onboarding_versions
Revises: 20261024_user_capabilities
"""
from alembic import op
import sqlalchemy as sa

revision = "20261103_onboarding_versions"
down_revision = "20261024_user_capabilities"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("company_profiles", "project_profiles"):
        op.add_column(table, sa.Column("published_snapshot", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("draft_revision", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    for table in ("project_profiles", "company_profiles"):
        op.drop_column(table, "draft_revision")
        op.drop_column(table, "published_snapshot")
