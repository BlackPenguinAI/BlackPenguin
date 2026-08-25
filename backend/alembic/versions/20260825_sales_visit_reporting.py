"""Add Sales visit reporting and secure meeting attachments.

Revision ID: 20260825_sales_visit
Revises: 20260825_sales_workspace
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260825_sales_visit"
down_revision = "20260825_sales_workspace"
branch_labels = None
depends_on = None


# SQLAlchemy persists Python Enum member names for this existing column.  API
# values remain lowercase through MeetingStatus.value, while PostgreSQL must
# receive the uppercase labels used by the ORM bind processor.
NEW_STATUSES = ("IN_PROGRESS", "COMPLETED_SALE_PENDING", "SALE_CLOSED")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in NEW_STATUSES:
            op.execute(sa.text(f"ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS '{value}'"))

    tables = set(inspect(bind).get_table_names())
    if "meetings" in tables:
        columns = {column["name"] for column in inspect(bind).get_columns("meetings")}
        with op.batch_alter_table("meetings") as batch:
            if "visit_notes" not in columns:
                batch.add_column(sa.Column("visit_notes", sa.Text(), nullable=True))
            if "visit_details" not in columns:
                batch.add_column(sa.Column("visit_details", sa.Text(), nullable=True))
            if "started_at" not in columns:
                batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
            if "completed_at" not in columns:
                batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
            if "sale_closed_at" not in columns:
                batch.add_column(sa.Column("sale_closed_at", sa.DateTime(), nullable=True))

    if "meeting_attachments" not in tables:
        op.create_table(
            "meeting_attachments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("meeting_id", sa.String(36), nullable=False),
            sa.Column("uploaded_by_user_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("storage_path", sa.Text(), nullable=False),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_meeting_attachments_meeting_id", "meeting_attachments", ["meeting_id"])


def downgrade() -> None:
    # Visit reports and evidence are operational records and are intentionally preserved.
    pass
