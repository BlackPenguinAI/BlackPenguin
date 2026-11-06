"""Add opt-in dialogue state and append-only service events, without backfill."""
from alembic import op
import sqlalchemy as sa

revision = '20261106_sales_dialogue'
down_revision = '20261104_inventory_confirmation'
branch_labels = None
depends_on = None


def scope_columns():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('company_id', sa.String(36), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
            sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.String(36), sa.ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('lead_id', sa.String(36), sa.ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)]


def upgrade():
    op.create_table('sales_dialogue_states', *scope_columns(),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('schema_version', sa.String(40), nullable=False),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('conversation_id', 'lead_id', name='uq_dialogue_state_scope'))
    op.create_index('ix_sales_dialogue_states_company_id', 'sales_dialogue_states', ['company_id'])
    op.create_table('sales_dialogue_events', *scope_columns(),
        sa.Column('event_key', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('state_after', sa.JSON(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('conversation_id', 'lead_id', 'event_key', name='uq_dialogue_event_key'),
        sa.UniqueConstraint('conversation_id', 'lead_id', 'revision', name='uq_dialogue_event_revision'))
    op.create_index('ix_sales_dialogue_events_company_id', 'sales_dialogue_events', ['company_id'])


def downgrade():
    # Explicit operator rollback only: events are evidence; archive before use.
    op.drop_table('sales_dialogue_events')
    op.drop_table('sales_dialogue_states')
