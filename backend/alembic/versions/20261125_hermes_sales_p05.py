"""Single global Hermes staff configuration with append-only version history.

Revision ID: 20261125_hermes_sales_p05
Revises: 20261125_hermes_sales_p04
"""
from alembic import op
import sqlalchemy as sa

revision = '20261125_hermes_sales_p05'
down_revision = '20261125_hermes_sales_p04'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hermes_global_settings',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('last_version', sa.Integer(), nullable=False),
        sa.Column('published_version_id', sa.String(36)),
        sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('hermes_global_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, unique=True),
        sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('change_note', sa.String(500), nullable=False),
        sa.Column('created_by_user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('is_published', sa.Boolean(), nullable=False))


def downgrade():
    # Operator-only rollback: archive these auditable publication records first.
    op.drop_table('hermes_global_versions')
    op.drop_table('hermes_global_settings')
