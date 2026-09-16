"""Compliance, operations, knowledge, KPI and notifications.

Revision ID: 20260915_compliance_ops
Revises: 20260907_project_receipts
"""

from alembic import op
import sqlalchemy as sa


revision = "20260915_compliance_ops"
down_revision = "20260907_project_receipts"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _add("users", sa.Column("deleted_by_user_id", sa.String(36), nullable=True))
    _add("users", sa.Column("deletion_reason", sa.String(500), nullable=True))
    _add("leads", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _add("leads", sa.Column("deleted_by_user_id", sa.String(36), nullable=True))
    _add("leads", sa.Column("deletion_reason", sa.Text(), nullable=True))
    for table in ("company_onboarding_sources", "company_media_assets", "project_onboarding_sources", "meeting_attachments"):
        _add(table, sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default=sa.false()))
        _add(table, sa.Column("content_hash", sa.String(64), nullable=True))
        _add(table, sa.Column("encryption_key_id", sa.String(64), nullable=True))
    _add("sales_asset_shares", sa.Column("first_human_access_at", sa.DateTime(), nullable=True))

    for index_name, table, column in (
        ("ix_users_deleted_at", "users", "deleted_at"),
        ("ix_leads_deleted_at", "leads", "deleted_at"),
    ):
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if index_name not in indexes:
            op.create_index(index_name, table, [column])

    tables = _tables()
    if "legal_document_versions" not in tables:
        op.create_table(
            "legal_document_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("doc_type", sa.String(50), nullable=False, index=True),
            sa.Column("language", sa.String(10), nullable=False, server_default="en"),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("content_markdown", sa.Text(), nullable=False),
            sa.Column("published_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("doc_type", "language", "version", name="uq_legal_document_version"),
        )
    if "user_legal_acceptances" not in tables:
        op.create_table(
            "user_legal_acceptances",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("invitation_id", sa.String(36), sa.ForeignKey("user_invitations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("privacy_version_id", sa.String(36), sa.ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("terms_version_id", sa.String(36), sa.ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("data_deletion_version_id", sa.String(36), sa.ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("user_agent_hash", sa.String(64), nullable=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "invitation_id", name="uq_user_invitation_legal_acceptance"),
        )
    if "platform_audit_events" not in tables:
        op.create_table(
            "platform_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("actor_role", sa.String(30), nullable=True),
            sa.Column("event_type", sa.String(80), nullable=False, index=True),
            sa.Column("entity_type", sa.String(60), nullable=True),
            sa.Column("entity_id", sa.String(36), nullable=True, index=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("request_id", sa.String(100), nullable=True, index=True),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("previous_hash", sa.String(64), nullable=True),
            sa.Column("event_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        )
    if "data_export_audit_events" not in tables:
        op.create_table(
            "data_export_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("actor_role", sa.String(30), nullable=False),
            sa.Column("export_type", sa.String(40), nullable=False, index=True),
            sa.Column("filters_json", sa.JSON(), nullable=False),
            sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("outcome", sa.String(30), nullable=False, server_default="generated", index=True),
            sa.Column("request_id", sa.String(100), nullable=True, index=True),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("previous_hash", sa.String(64), nullable=True),
            sa.Column("event_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        )
    if "agent_operating_policies" not in tables:
        op.create_table(
            "agent_operating_policies",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
            sa.Column("weekly_windows", sa.JSON(), nullable=False),
            sa.Column("blackout_dates", sa.JSON(), nullable=False),
            sa.Column("enforce_manual_messages", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "project_id", name="uq_agent_operating_policy_scope"),
        )
    if "knowledge_guidance_items" not in tables:
        op.create_table(
            "knowledge_guidance_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("kind", sa.String(20), nullable=False, index=True),
            sa.Column("title", sa.String(220), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if "conversation_kpi_targets" not in tables:
        op.create_table(
            "conversation_kpi_targets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("response_rate_percent", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("conversation_turns_min", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("conversation_turns_max", sa.Integer(), nullable=False, server_default="12"),
            sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "project_id", name="uq_conversation_kpi_target_scope"),
        )
    if "human_intervention_cases" not in tables:
        op.create_table(
            "human_intervention_cases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("reason", sa.String(60), nullable=False, index=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("confidence", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
            sa.Column("dedupe_key", sa.String(160), nullable=False),
            sa.Column("resolved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("conversation_id", "dedupe_key", name="uq_intervention_case_dedupe"),
        )
    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("notification_type", sa.String(60), nullable=False, index=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("title", sa.String(180), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.String(60), nullable=True),
            sa.Column("entity_id", sa.String(36), nullable=True),
            sa.Column("action_url", sa.String(500), nullable=True),
            sa.Column("dedupe_key", sa.String(180), nullable=False),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
            sa.UniqueConstraint("recipient_user_id", "dedupe_key", name="uq_notification_recipient_dedupe"),
        )
    if "notification_outbox" not in tables:
        op.create_table(
            "notification_outbox",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("event_type", sa.String(60), nullable=False, index=True),
            sa.Column("entity_type", sa.String(60), nullable=True),
            sa.Column("entity_id", sa.String(36), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("dedupe_key", sa.String(180), nullable=False, unique=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if "sales_asset_access_events" not in tables:
        op.create_table(
            "sales_asset_access_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("share_id", sa.String(36), sa.ForeignKey("sales_asset_shares.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("event_type", sa.String(20), nullable=False, index=True),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("user_agent_hash", sa.String(64), nullable=True),
            sa.Column("is_automated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        )

    inspector = sa.inspect(op.get_bind())
    policy_indexes = {item["name"] for item in inspector.get_indexes("agent_operating_policies")}
    if "uq_agent_operating_policy_company_default" not in policy_indexes:
        op.create_index(
            "uq_agent_operating_policy_company_default", "agent_operating_policies", ["company_id"],
            unique=True, postgresql_where=sa.text("project_id IS NULL"), sqlite_where=sa.text("project_id IS NULL"),
        )
    kpi_indexes = {item["name"] for item in inspector.get_indexes("conversation_kpi_targets")}
    if "uq_conversation_kpi_target_company_default" not in kpi_indexes:
        op.create_index(
            "uq_conversation_kpi_target_company_default", "conversation_kpi_targets", ["company_id"],
            unique=True, postgresql_where=sa.text("project_id IS NULL"), sqlite_where=sa.text("project_id IS NULL"),
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION bp_reject_audit_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'audit events are immutable'; END; $$ LANGUAGE plpgsql;
        """)
        for table in ("platform_audit_events", "data_export_audit_events"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bp_reject_audit_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("platform_audit_events", "data_export_audit_events"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
        op.execute("DROP FUNCTION IF EXISTS bp_reject_audit_mutation")
    if "conversation_kpi_targets" in _tables():
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("conversation_kpi_targets")}
        if "uq_conversation_kpi_target_company_default" in indexes:
            op.drop_index("uq_conversation_kpi_target_company_default", table_name="conversation_kpi_targets")
    if "agent_operating_policies" in _tables():
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("agent_operating_policies")}
        if "uq_agent_operating_policy_company_default" in indexes:
            op.drop_index("uq_agent_operating_policy_company_default", table_name="agent_operating_policies")
    for table in (
        "sales_asset_access_events", "notification_outbox", "notifications",
        "human_intervention_cases", "conversation_kpi_targets", "knowledge_guidance_items",
        "agent_operating_policies", "data_export_audit_events", "platform_audit_events",
        "user_legal_acceptances", "legal_document_versions",
    ):
        if table in _tables():
            op.drop_table(table)
    for table, columns in (
        ("sales_asset_shares", ("first_human_access_at",)),
        ("company_media_assets", ("encryption_key_id", "content_hash", "is_encrypted")),
        ("company_onboarding_sources", ("encryption_key_id", "content_hash", "is_encrypted")),
        ("meeting_attachments", ("encryption_key_id", "content_hash", "is_encrypted")),
        ("project_onboarding_sources", ("encryption_key_id", "content_hash", "is_encrypted")),
        ("leads", ("deletion_reason", "deleted_by_user_id", "deleted_at")),
        ("users", ("deletion_reason", "deleted_by_user_id", "deleted_at")),
    ):
        if table not in _tables():
            continue
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        deleted_index = f"ix_{table}_deleted_at"
        if deleted_index in indexes:
            op.drop_index(deleted_index, table_name=table)
        for column in columns:
            if column in _columns(table):
                op.drop_column(table, column)
