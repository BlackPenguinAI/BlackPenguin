"""Add durable first-booking receipts; leave historical meetings unchanged."""
from alembic import op
import sqlalchemy as sa
revision='20261108_sales_booking_ops'
down_revision='20261108_sales_visit_context'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sales_booking_operations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('company_id',sa.String(36),sa.ForeignKey('companies.id',ondelete='CASCADE'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('conversation_id',sa.String(36),sa.ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('lead_id',sa.String(36),sa.ForeignKey('leads.id',ondelete='CASCADE'),nullable=False),
        sa.Column('proposal_id',sa.String(64),nullable=False,unique=True),
        sa.Column('meeting_id',sa.String(36),sa.ForeignKey('meetings.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('snapshot_json',sa.JSON(),nullable=False),
        sa.Column('calendar_status',sa.String(30),nullable=False),
        sa.Column('calendar_attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt_at',sa.DateTime(),nullable=False),
        sa.Column('last_error',sa.String(100),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_sales_booking_operations_calendar_status','sales_booking_operations',['calendar_status'])


def downgrade():
    op.drop_index('ix_sales_booking_operations_calendar_status',table_name='sales_booking_operations')
    op.drop_table('sales_booking_operations')
