"""Add scoped moderation evidence and warning receipts without rewriting messages."""
from alembic import op
import sqlalchemy as sa
revision='20261108_sales_moderation'
down_revision='20261108_sales_wait_requests'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sales_moderation_incidents',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('company_id',sa.String(36),sa.ForeignKey('companies.id',ondelete='CASCADE'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('conversation_id',sa.String(36),sa.ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('lead_id',sa.String(36),sa.ForeignKey('leads.id',ondelete='CASCADE'),nullable=False),
        sa.Column('message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False),
        sa.Column('event_key',sa.String(300),nullable=False),sa.Column('category',sa.String(30),nullable=False),
        sa.Column('evidence',sa.String(2000),nullable=False),sa.Column('disposition',sa.String(30),nullable=False),
        sa.Column('prior_warning_id',sa.String(36),sa.ForeignKey('sales_moderation_incidents.id',ondelete='SET NULL')),
        sa.Column('warning_message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='SET NULL')),
        sa.Column('warning_accepted_at',sa.DateTime()),
        sa.Column('intervention_case_id',sa.String(36),sa.ForeignKey('human_intervention_cases.id',ondelete='SET NULL')),
        sa.Column('dismissed_at',sa.DateTime()),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('conversation_id','event_key',name='uq_sales_moderation_event'))


def downgrade():op.drop_table('sales_moderation_incidents')
