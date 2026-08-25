"""Add user and Project IANA timezones for scheduling.

Revision ID: 20260825_schedule_tz
Revises: 20260825_sales_visit
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260825_schedule_tz"
down_revision = "20260825_sales_visit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name in ("users", "projects"):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspect(bind).get_columns(table_name)}
        if "timezone" not in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"))


def downgrade() -> None:
    # Timezones are user/project business data and are intentionally preserved.
    pass
