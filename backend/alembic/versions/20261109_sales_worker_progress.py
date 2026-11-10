"""Record Sales queue progress independently of the onboarding heartbeat."""
from alembic import op
import sqlalchemy as sa
revision='20261109_sales_worker_progress'
down_revision='20261109_sales_continuity'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sales_worker_progress',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('commit_sha',sa.String(64),nullable=False),sa.Column('progress_json',sa.JSON(),nullable=False),
        sa.Column('last_progress_at',sa.DateTime(),nullable=False),sa.Column('stopped_at',sa.DateTime(),nullable=True))
    op.create_index('ix_sales_worker_progress_last_progress_at','sales_worker_progress',['last_progress_at'])


def downgrade():
    op.drop_index('ix_sales_worker_progress_last_progress_at',table_name='sales_worker_progress')
    op.drop_table('sales_worker_progress')
