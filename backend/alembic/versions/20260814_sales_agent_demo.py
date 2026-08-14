"""Adopt or create persistent sales-agent conversation tables.

Revision ID: 20260814_sales_agent_demo
Revises: 20260814_company_catalog_media

Some production databases already contain these tables because older startup
code loaded the SQLAlchemy metadata before Alembic owned the schema.  This
revision therefore adopts compatible existing tables and only creates missing
objects.  Its downgrade is intentionally non-destructive because Alembic cannot
know whether a table was created here or predates this revision.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260814_sales_agent_demo"
down_revision = "20260814_company_catalog_media"
branch_labels = None
depends_on = None


TABLE_COLUMNS: dict[str, set[str]] = {
    "sales_conversations": {
        "id", "company_id", "project_id", "campaign_id", "lead_id", "channel",
        "stage", "automation_level", "is_paused", "pause_reason", "created_at", "updated_at",
    },
    "sales_messages": {
        "id", "conversation_id", "channel", "direction", "role", "content",
        "provider_message_id", "status", "metadata_json", "created_at",
    },
    "agent_runs": {
        "id", "conversation_id", "event_id", "mode", "status", "graph_version",
        "toolset_version", "prompt_configuration_id", "prompt_snapshot", "model",
        "input_snapshot", "output_snapshot", "token_usage", "estimated_cost_usd",
        "error_code", "started_at", "completed_at",
    },
    "outbound_messages": {
        "id", "conversation_id", "agent_run_id", "idempotency_key", "channel",
        "recipient", "content", "status", "approved_by_user_id", "approved_at",
        "sent_at", "last_error", "created_at",
    },
    "external_webhook_events": {
        "id", "platform", "external_event_id", "event_type", "payload_json", "status",
        "error_message", "received_at", "processed_at",
    },
}


def _validate_existing_table(table_name: str) -> None:
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}
    missing = TABLE_COLUMNS[table_name] - existing
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}; required columns are missing: {names}."
        )


def _ensure_indexes(table_name: str, specifications: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    existing = {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }
    for name, columns in specifications:
        if name not in existing:
            op.create_index(name, table_name, list(columns))


def _ensure_unique(table_name: str, name: str, columns: tuple[str, ...]) -> None:
    expected = set(columns)
    constraints = inspect(op.get_bind()).get_unique_constraints(table_name)
    if not any(set(item.get("column_names") or []) == expected for item in constraints):
        op.create_unique_constraint(name, table_name, list(columns))


def _ensure_foreign_key(
    table_name: str,
    name: str,
    local_columns: tuple[str, ...],
    remote_table: str,
    remote_columns: tuple[str, ...],
    ondelete: str,
) -> None:
    expected_local = set(local_columns)
    constraints = inspect(op.get_bind()).get_foreign_keys(table_name)
    if any(
        set(item.get("constrained_columns") or []) == expected_local
        and item.get("referred_table") == remote_table
        for item in constraints
    ):
        return
    op.create_foreign_key(
        name, table_name, remote_table, list(local_columns), list(remote_columns), ondelete=ondelete,
    )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "sales_conversations" not in tables:
        op.create_table(
            "sales_conversations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=True),
            sa.Column("lead_id", sa.String(36), nullable=False),
            sa.Column("channel", sa.String(30), nullable=False),
            sa.Column("stage", sa.String(40), nullable=False, server_default="new"),
            sa.Column("automation_level", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("pause_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["campaign_id"], ["project_campaigns.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("lead_id", "channel", name="uq_sales_conversation_lead_channel"),
        )
    else:
        _validate_existing_table("sales_conversations")
        _ensure_unique("sales_conversations", "uq_sales_conversation_lead_channel", ("lead_id", "channel"))
        _ensure_foreign_key("sales_conversations", "fk_sales_conversations_company", ("company_id",), "companies", ("id",), "CASCADE")
        _ensure_foreign_key("sales_conversations", "fk_sales_conversations_project", ("project_id",), "projects", ("id",), "CASCADE")
        _ensure_foreign_key("sales_conversations", "fk_sales_conversations_campaign", ("campaign_id",), "project_campaigns", ("id",), "SET NULL")
        _ensure_foreign_key("sales_conversations", "fk_sales_conversations_lead", ("lead_id",), "leads", ("id",), "CASCADE")
    _ensure_indexes("sales_conversations", tuple(
        (f"ix_sales_conversations_{column}", (column,))
        for column in ("company_id", "project_id", "campaign_id", "lead_id", "stage", "updated_at")
    ))

    if "sales_messages" not in tables:
        op.create_table(
            "sales_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("channel", sa.String(30), nullable=False),
            sa.Column("direction", sa.String(20), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("provider_message_id", sa.String(180), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="received"),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("channel", "provider_message_id", name="uq_sales_message_provider_id"),
        )
    else:
        _validate_existing_table("sales_messages")
        _ensure_unique("sales_messages", "uq_sales_message_provider_id", ("channel", "provider_message_id"))
        _ensure_foreign_key("sales_messages", "fk_sales_messages_conversation", ("conversation_id",), "sales_conversations", ("id",), "CASCADE")
    _ensure_indexes("sales_messages", (
        ("ix_sales_messages_conversation_id", ("conversation_id",)),
        ("ix_sales_messages_created_at", ("created_at",)),
    ))

    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("event_id", sa.String(180), nullable=False, unique=True),
            sa.Column("mode", sa.String(20), nullable=False, server_default="simulation"),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("graph_version", sa.String(30), nullable=False),
            sa.Column("toolset_version", sa.String(30), nullable=False),
            sa.Column("prompt_configuration_id", sa.String(36), nullable=True),
            sa.Column("prompt_snapshot", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(180), nullable=False),
            sa.Column("input_snapshot", sa.JSON(), nullable=False),
            sa.Column("output_snapshot", sa.JSON(), nullable=False),
            sa.Column("token_usage", sa.JSON(), nullable=False),
            sa.Column("estimated_cost_usd", sa.String(30), nullable=True),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
        )
    else:
        _validate_existing_table("agent_runs")
        _ensure_unique("agent_runs", "uq_agent_runs_event_id", ("event_id",))
        _ensure_foreign_key("agent_runs", "fk_agent_runs_conversation", ("conversation_id",), "sales_conversations", ("id",), "CASCADE")
    _ensure_indexes("agent_runs", (("ix_agent_runs_conversation_id", ("conversation_id",)),))

    if "outbound_messages" not in tables:
        op.create_table(
            "outbound_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("agent_run_id", sa.String(36), nullable=False),
            sa.Column("idempotency_key", sa.String(220), nullable=False, unique=True),
            sa.Column("channel", sa.String(30), nullable=False),
            sa.Column("recipient", sa.String(180), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("approved_by_user_id", sa.String(36), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["sales_conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
    else:
        _validate_existing_table("outbound_messages")
        _ensure_unique("outbound_messages", "uq_outbound_messages_idempotency_key", ("idempotency_key",))
        _ensure_foreign_key("outbound_messages", "fk_outbound_messages_conversation", ("conversation_id",), "sales_conversations", ("id",), "CASCADE")
        _ensure_foreign_key("outbound_messages", "fk_outbound_messages_run", ("agent_run_id",), "agent_runs", ("id",), "CASCADE")
        _ensure_foreign_key("outbound_messages", "fk_outbound_messages_approver", ("approved_by_user_id",), "users", ("id",), "SET NULL")
    _ensure_indexes("outbound_messages", (
        ("ix_outbound_messages_conversation_id", ("conversation_id",)),
        ("ix_outbound_messages_agent_run_id", ("agent_run_id",)),
        ("ix_outbound_messages_status", ("status",)),
    ))

    if "external_webhook_events" not in tables:
        op.create_table(
            "external_webhook_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("platform", sa.String(30), nullable=False),
            sa.Column("external_event_id", sa.String(180), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="received"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("platform", "external_event_id", name="uq_webhook_platform_event"),
        )
    else:
        _validate_existing_table("external_webhook_events")
        _ensure_unique("external_webhook_events", "uq_webhook_platform_event", ("platform", "external_event_id"))

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
    """Unregister the revision without deleting adopted production data."""
    if "schema_versions" in set(inspect(op.get_bind()).get_table_names()):
        op.execute(
            sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision)
        )
