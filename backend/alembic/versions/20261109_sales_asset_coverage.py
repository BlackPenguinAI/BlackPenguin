"""Add reviewed multi-target content coverage without rewriting legacy approvals."""
from alembic import op
import sqlalchemy as sa
revision='20261109_sales_asset_coverage'
down_revision='20261108_sales_moderation'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('project_sales_assets',sa.Column('coverage',sa.JSON(none_as_null=True),nullable=True))


def downgrade():
    # Never turn a newly targeted approval into a Project-wide legacy asset.
    op.execute(sa.text("UPDATE sales_asset_shares SET revoked = true, revoked_at = CURRENT_TIMESTAMP WHERE sales_asset_id IN (SELECT id FROM project_sales_assets WHERE coverage IS NOT NULL)"))
    op.execute(sa.text("UPDATE project_sales_assets SET approval_status = 'draft', approved_at = NULL, approved_by_user_id = NULL, version = version + 1 WHERE coverage IS NOT NULL"))
    op.drop_column('project_sales_assets','coverage')
