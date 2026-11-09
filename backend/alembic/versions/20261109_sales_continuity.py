"""Durable resume and inactivity episodes; no historical message replay."""
from alembic import op
import sqlalchemy as sa

revision='20261109_sales_continuity'
down_revision='20261109_sales_asset_coverage'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('sales_conversations',sa.Column('continuity_json',sa.JSON(),nullable=False,server_default=sa.text("'{}'")))
    op.add_column('sales_follow_up_jobs',sa.Column('kind',sa.String(30),nullable=False,server_default='cadence'))
    op.add_column('sales_follow_up_jobs',sa.Column('payload_json',sa.JSON(),nullable=False,server_default=sa.text("'{}'")))
    op.add_column('sales_follow_up_jobs',sa.Column('claimed_at',sa.DateTime(),nullable=True))
    op.create_index('ix_sales_follow_up_jobs_kind','sales_follow_up_jobs',['kind'])


def downgrade():
    # Old workers must never send these as nurture messages after rollback.
    op.execute(sa.text("DELETE FROM sales_follow_up_jobs WHERE kind IN ('resume','inactivity')"))
    op.drop_index('ix_sales_follow_up_jobs_kind',table_name='sales_follow_up_jobs')
    op.drop_column('sales_follow_up_jobs','claimed_at')
    op.drop_column('sales_follow_up_jobs','payload_json')
    op.drop_column('sales_follow_up_jobs','kind')
    op.drop_column('sales_conversations','continuity_json')
