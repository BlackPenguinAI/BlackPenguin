"""Live Twilio agent, Lead Record intelligence and prompt history.

Revision ID: 20260830_live_sales_agent
Revises: 20260826_user_project_access
"""

from alembic import op
import sqlalchemy as sa

revision = "20260830_live_sales_agent"
down_revision = "20260826_user_project_access"
branch_labels = None
depends_on = None


def _tables(): return set(sa.inspect(op.get_bind()).get_table_names())
def _columns(table): return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
def _indexes(table): return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
def _has_fk(table, column, referred_table):
    return any(
        column in (item.get("constrained_columns") or []) and item.get("referred_table") == referred_table
        for item in sa.inspect(op.get_bind()).get_foreign_keys(table)
    )
def _add(table, column):
    if table in _tables() and column.name not in _columns(table): op.add_column(table, column)


def upgrade():
    _add("twilio_configurations", sa.Column("auth_token_ciphertext", sa.Text(), nullable=True))
    _add("twilio_configurations", sa.Column("auth_token_hint", sa.String(12), nullable=True))
    _add("twilio_configurations", sa.Column("live_sms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add("twilio_configurations", sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"))
    _add("twilio_configurations", sa.Column("verified_at", sa.DateTime(), nullable=True))
    _add("twilio_configurations", sa.Column("last_error", sa.Text(), nullable=True))
    if "twilio_configurations" in _tables():
        op.execute(sa.text("UPDATE twilio_configurations SET from_phone_number = COALESCE(NULLIF(from_phone_number, ''), '+18573824206')"))

    if "lead_contacts" not in _tables():
        op.create_table("lead_contacts",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("company_id", sa.String(36), nullable=False),
            sa.Column("canonical_phone", sa.String(50), nullable=False), sa.Column("full_name", sa.String(150)),
            sa.Column("email", sa.String(150)), sa.Column("preferred_language", sa.String(10)), sa.Column("preferred_channel", sa.String(30)),
            sa.Column("previous_projects", sa.JSON(), nullable=False, server_default="[]"), sa.Column("lifetime_value", sa.Numeric(16,2)),
            sa.Column("vip_flag", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.UniqueConstraint("company_id", "canonical_phone", name="uq_lead_contact_company_phone"))
        op.create_index("ix_lead_contacts_company_id", "lead_contacts", ["company_id"])
    _add("leads", sa.Column("contact_id", sa.String(36), nullable=True))
    _add("leads", sa.Column("intent_tier", sa.String(20), nullable=False, server_default="cold"))
    _add("leads", sa.Column("assigned_segment", sa.String(60), nullable=True))
    _add("leads", sa.Column("buyer_type", sa.String(30), nullable=True))
    _add("leads", sa.Column("pipeline_stage", sa.String(40), nullable=False, server_default="S00_CAPTURE"))
    if not _has_fk("leads", "contact_id", "lead_contacts"):
        with op.batch_alter_table("leads") as batch:
            batch.create_foreign_key("fk_leads_contact_id_lead_contacts", "lead_contacts", ["contact_id"], ["id"], ondelete="SET NULL")
    for name in ("contact_id", "intent_tier", "assigned_segment", "pipeline_stage"):
        index_name = f"ix_leads_{name}"
        if index_name not in _indexes("leads"): op.create_index(index_name, "leads", [name])

    definitions = {
        "lead_score_snapshots": [sa.Column("id", sa.String(36), primary_key=True), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("total_score", sa.Integer(), nullable=False), sa.Column("assigned_tier", sa.String(20), nullable=False), sa.Column("factor_breakdown", sa.JSON(), nullable=False), sa.Column("scoring_version", sa.String(40), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False)],
        "lead_segment_assignments": [sa.Column("id", sa.String(36), primary_key=True), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("segment", sa.String(60), nullable=False), sa.Column("confidence", sa.Numeric(3,2), nullable=False), sa.Column("reasons", sa.JSON(), nullable=False), sa.Column("strategy_version", sa.String(40), nullable=False), sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(), nullable=False)],
        "lead_objections": [sa.Column("id", sa.String(36), primary_key=True), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("objection_type", sa.String(30), nullable=False), sa.Column("evidence", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="open"), sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False)],
        "lead_consent_events": [sa.Column("id", sa.String(36), primary_key=True), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("channel", sa.String(30), nullable=False), sa.Column("action", sa.String(30), nullable=False), sa.Column("source", sa.String(60), nullable=False), sa.Column("policy_version", sa.String(40)), sa.Column("evidence", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False)],
    }
    for table, columns in definitions.items():
        if table not in _tables():
            op.create_table(table, *columns, sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"))
            op.create_index(f"ix_{table}_lead_id", table, ["lead_id"])

    _add("sales_conversations", sa.Column("provider_thread_key", sa.String(220), nullable=True))
    if "ux_sales_conversations_provider_thread_key" not in _indexes("sales_conversations"):
        op.create_index("ux_sales_conversations_provider_thread_key", "sales_conversations", ["provider_thread_key"], unique=True)
    _add("sales_messages", sa.Column("author_user_id", sa.String(36), nullable=True))
    if not _has_fk("sales_messages", "author_user_id", "users"):
        with op.batch_alter_table("sales_messages") as batch:
            batch.create_foreign_key("fk_sales_messages_author_user_id_users", "users", ["author_user_id"], ["id"], ondelete="SET NULL")
    if "ix_sales_messages_author_user_id" not in _indexes("sales_messages"):
        op.create_index("ix_sales_messages_author_user_id", "sales_messages", ["author_user_id"])
    if "outbound_messages" in _tables():
        _add("outbound_messages", sa.Column("provider_message_id", sa.String(180), nullable=True))
        if "ux_outbound_messages_provider_message_id" not in _indexes("outbound_messages"):
            op.create_index("ux_outbound_messages_provider_message_id", "outbound_messages", ["provider_message_id"], unique=True)
        with op.batch_alter_table("outbound_messages") as batch: batch.alter_column("agent_run_id", existing_type=sa.String(36), nullable=True)

    if "prompt_versions" not in _tables():
        op.create_table("prompt_versions",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("company_id", sa.String(36), nullable=True),
            sa.Column("agent_key", sa.String(60), nullable=False), sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("configuration", sa.JSON(), nullable=False), sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.String(36), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("published_at", sa.DateTime()),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("company_id", "agent_key", "version_number", name="uq_prompt_scope_agent_version"))
        op.create_index("ix_prompt_versions_company_id", "prompt_versions", ["company_id"])
        op.create_index("ix_prompt_versions_agent_key", "prompt_versions", ["agent_key"])


def downgrade():
    # Deliberately non-destructive: provider and Lead Record history is retained.
    pass
