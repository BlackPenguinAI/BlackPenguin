"""Hermes Sales state/events, additive and disabled until future routing release.

Revision ID: 20261125_hermes_sales_p03
Revises: 20261109_sales_worker_progress
"""
from alembic import op
import sqlalchemy as sa

revision = '20261125_hermes_sales_p03'
down_revision = '20261109_sales_worker_progress'
branch_labels = None
depends_on = None


def _scope():
    return [
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lead_id', sa.String(36), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False),
    ]


def upgrade():
    op.create_table(
        'hermes_sales_states', *_scope(),
        sa.Column('engine_version', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.String(40), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('conversation_id', 'lead_id', name='uq_hermes_state_opportunity'),
    )
    op.create_index('ix_hermes_sales_states_company_id', 'hermes_sales_states', ['company_id'])
    op.create_table(
        'hermes_sales_state_events', *_scope(),
        sa.Column('event_key', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(36), nullable=False),
        sa.Column('schema_version', sa.String(40), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('state_after', sa.JSON(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('conversation_id', 'lead_id', 'event_key', name='uq_hermes_state_event_key'),
        sa.UniqueConstraint('conversation_id', 'lead_id', 'revision', name='uq_hermes_state_event_revision'),
    )
    op.create_index('ix_hermes_sales_state_events_company_id', 'hermes_sales_state_events', ['company_id'])


def downgrade():
    # An operator MUST archive state evidence before running a rollback.
    op.drop_index('ix_hermes_sales_state_events_company_id', table_name='hermes_sales_state_events')
    op.drop_table('hermes_sales_state_events')
    op.drop_index('ix_hermes_sales_states_company_id', table_name='hermes_sales_states')
    op.drop_table('hermes_sales_states')
