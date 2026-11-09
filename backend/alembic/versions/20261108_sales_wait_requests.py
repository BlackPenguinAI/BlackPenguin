"""Persist scoped, expiring availability alerts; do not change reservations."""
from alembic import op
import sqlalchemy as sa
revision='20261108_sales_wait_requests'
down_revision='20261108_sales_cancel_ops'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sales_wait_requests',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('company_id',sa.String(36),sa.ForeignKey('companies.id',ondelete='CASCADE'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('target_project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('conversation_id',sa.String(36),sa.ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('lead_id',sa.String(36),sa.ForeignKey('leads.id',ondelete='CASCADE'),nullable=False),
        sa.Column('requested_message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False),
        sa.Column('active_key',sa.String(64),unique=True),sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('snapshot_json',sa.JSON(),nullable=False),sa.Column('channel',sa.String(20),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('close_reason',sa.String(100)),
        sa.Column('expires_at',sa.DateTime(),nullable=False),sa.Column('next_check_at',sa.DateTime(),nullable=False),
        sa.Column('lease_until',sa.DateTime()),sa.Column('claim_token',sa.String(36)),sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('last_error',sa.String(100)),
        sa.Column('scan_date',sa.String(10)),sa.Column('notice_json',sa.JSON()),sa.Column('anchor_revision',sa.Integer()),sa.Column('anchor_inbound_id',sa.String(36)),
        sa.Column('notified_message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('closed_at',sa.DateTime()))
    op.create_index('ix_sales_wait_requests_status','sales_wait_requests',['status'])


def downgrade():
    op.drop_index('ix_sales_wait_requests_status',table_name='sales_wait_requests')
    op.drop_table('sales_wait_requests')
