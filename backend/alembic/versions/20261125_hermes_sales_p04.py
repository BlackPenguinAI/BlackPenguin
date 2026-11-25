"""Add Hermes-only simulation operation receipts; no legacy data backfill.

P04 creates no message dispatch or production agent routing.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261125_hermes_sales_p04'
down_revision = '20261125_hermes_sales_p03'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hermes_sales_operations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('company_id',sa.String(36),sa.ForeignKey('companies.id',ondelete='CASCADE'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('conversation_id',sa.String(36),sa.ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('lead_id',sa.String(36),sa.ForeignKey('leads.id',ondelete='CASCADE'),nullable=False),
        sa.Column('inbound_message_id',sa.String(36),sa.ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False),
        sa.Column('request_id',sa.String(64),nullable=False),
        sa.Column('operation_type',sa.String(24),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('result_json',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('conversation_id','lead_id','request_id',name='uq_hermes_sales_operation_request'),
    )
    op.create_index('ix_hermes_sales_operations_company_id','hermes_sales_operations',['company_id'])


def downgrade():
    # Explicit downgrade destroys the P04 audit table: archive before use.
    op.drop_index('ix_hermes_sales_operations_company_id',table_name='hermes_sales_operations')
    op.drop_table('hermes_sales_operations')
