"""Add cancellation receipts; preserve all historical reservations and existing outboxes."""
from alembic import op
import sqlalchemy as sa
revision='20261108_sales_cancel_ops'
down_revision='20261108_sales_reschedule_ops'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sales_cancellation_operations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('company_id',sa.String(36),sa.ForeignKey('companies.id',ondelete='CASCADE'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('booking_project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('conversation_id',sa.String(36),sa.ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('lead_id',sa.String(36),sa.ForeignKey('leads.id',ondelete='CASCADE'),nullable=False),
        sa.Column('proposal_id',sa.String(64),nullable=False,unique=True),
        sa.Column('meeting_id',sa.String(36),sa.ForeignKey('meetings.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('snapshot_json',sa.JSON(),nullable=False),
        sa.Column('calendar_status',sa.String(40),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt_at',sa.DateTime(),nullable=False),
        sa.Column('last_error',sa.String(100)),
        sa.Column('notification_outbox_id',sa.String(36),sa.ForeignKey('notification_outbox.id',ondelete='SET NULL')),
        sa.Column('notification_status',sa.String(30),nullable=False),
        sa.Column('notification_attempts',sa.Integer(),nullable=False),
        sa.Column('notification_next_attempt_at',sa.DateTime(),nullable=False),
        sa.Column('notification_last_error',sa.String(100)),
        sa.Column('reason',sa.Text()),
        sa.Column('reason_message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_sales_cancellation_operations_calendar_status','sales_cancellation_operations',['calendar_status'])


def downgrade():
    op.drop_index('ix_sales_cancellation_operations_calendar_status',table_name='sales_cancellation_operations')
    op.drop_table('sales_cancellation_operations')
