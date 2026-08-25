"""Add date-specific Sales availability and lead visit context.

Revision ID: 20260825_sales_workspace
Revises: 20260818_multi_demo
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260825_sales_workspace"
down_revision = "20260818_multi_demo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "leads" in tables:
        columns = {column["name"] for column in inspect(bind).get_columns("leads")}
        with op.batch_alter_table("leads") as batch:
            if "meta_form_data" not in columns:
                batch.add_column(sa.Column("meta_form_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
            if "visit_recommendations" not in columns:
                batch.add_column(sa.Column("visit_recommendations", sa.Text(), nullable=True))

    if "sales_availability_blocks" not in tables:
        op.create_table(
            "sales_availability_blocks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("starts_at", sa.DateTime(), nullable=False),
            sa.Column("ends_at", sa.DateTime(), nullable=False),
            sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "starts_at", "ends_at", name="uq_sales_availability_block"),
        )
        op.create_index("ix_sales_availability_blocks_user_id", "sales_availability_blocks", ["user_id"])
        op.create_index("ix_sales_availability_blocks_starts_at", "sales_availability_blocks", ["starts_at"])
        op.create_index("ix_sales_availability_blocks_ends_at", "sales_availability_blocks", ["ends_at"])


def downgrade() -> None:
    # Operational Sales availability and captured lead context are preserved.
    pass
