"""Add the tenant-safe sales-agent simulation and scheduling foundation.

Revision ID: 20260817_agent_simulation
Revises: 20260814_sales_agent_demo

The migration is additive and adopts the legacy calendar_connections table
when it already exists.  Its downgrade intentionally preserves operational
data, matching the repository's adoption migrations.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260817_agent_simulation"
down_revision = "20260814_sales_agent_demo"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {
        item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def _ensure_index(table_name: str, name: str, columns: tuple[str, ...]) -> None:
    if name not in _indexes(table_name):
        op.create_index(name, table_name, list(columns))


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())

    if "meetings" in tables:
        existing = _columns("meetings")
        with op.batch_alter_table("meetings") as batch:
            if "is_demo" not in existing:
                batch.add_column(sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "source" not in existing:
                batch.add_column(sa.Column("source", sa.String(40), nullable=False, server_default="manual"))
            batch.alter_column("broker_id", existing_type=sa.String(36), nullable=True)
        _ensure_index("meetings", "ix_meetings_is_demo", ("is_demo",))

    if "sales_agent_simulations" not in tables:
        op.create_table(
            "sales_agent_simulations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=False),
            sa.Column("lead_id", sa.String(36), nullable=False, unique=True),
            sa.Column("conversation_id", sa.String(36), nullable=False, unique=True),
            sa.Column("created_by_user_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="active"),
            sa.Column("approval_status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("approval_notes", sa.Text(), nullable=True),
            sa.Column("form_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("prompt_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("virtual_now", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["campaign_id"], ["project_campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
    for column in ("company_id", "project_id", "campaign_id", "status"):
        _ensure_index("sales_agent_simulations", f"ix_sales_agent_simulations_{column}", (column,))

    if "sales_follow_up_jobs" not in tables:
        op.create_table(
            "sales_follow_up_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("idempotency_key", sa.String(220), nullable=False, unique=True),
            sa.Column("scheduled_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("reason", sa.String(120), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
        )
    for column in ("conversation_id", "scheduled_at", "status"):
        _ensure_index("sales_follow_up_jobs", f"ix_sales_follow_up_jobs_{column}", (column,))

    if "sales_availability_windows" not in tables:
        op.create_table(
            "sales_availability_windows",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(5), nullable=False),
            sa.Column("end_time", sa.String(5), nullable=False),
            sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "weekday", "start_time", "end_time", name="uq_sales_availability_window"),
        )
    _ensure_index("sales_availability_windows", "ix_sales_availability_windows_user_id", ("user_id",))

    if "calendar_connections" not in tables:
        op.create_table(
            "calendar_connections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("provider", sa.String(30), nullable=False),
            sa.Column("calendar_id", sa.String(255), nullable=True),
            sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
            sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(), nullable=True),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("sync_token", sa.Text(), nullable=True),
            sa.Column("watch_channel_id", sa.String(255), nullable=True),
            sa.Column("watch_resource_id", sa.String(255), nullable=True),
            sa.Column("watch_expires_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="simulation"),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "provider", name="uq_calendar_connection_user_provider"),
        )
    else:
        required = {"id", "user_id", "provider", "calendar_id", "status"}
        missing = required - _columns("calendar_connections")
        if missing:
            raise RuntimeError(
                "Cannot adopt calendar_connections; required columns are missing: "
                + ", ".join(sorted(missing))
            )
    _ensure_index("calendar_connections", "ix_calendar_connections_user_id", ("user_id",))

    if "schema_versions" not in tables:
        op.create_table(
            "schema_versions",
            sa.Column("version", sa.String(100), primary_key=True),
            sa.Column("applied_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    op.execute(sa.text(
        "INSERT INTO schema_versions (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP) "
        "ON CONFLICT (version) DO NOTHING"
    ).bindparams(version=revision))


def downgrade() -> None:
    if "schema_versions" in set(inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision))
