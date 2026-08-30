"""Platform integrations and governed prompt metadata.

Revision ID: 20260831_platform_experience
Revises: 20260830_live_sales_agent
"""

from alembic import op
import sqlalchemy as sa

revision = "20260831_platform_experience"
down_revision = "20260830_live_sales_agent"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "google_calendar_configurations" not in _tables():
        op.create_table(
            "google_calendar_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("client_id", sa.String(255), nullable=True),
            sa.Column("client_secret_ciphertext", sa.Text(), nullable=True),
            sa.Column("client_secret_hint", sa.String(12), nullable=True),
            sa.Column("redirect_uri", sa.String(500), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "calendar_oauth_attempts" not in _tables():
        op.create_table(
            "calendar_oauth_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("nonce_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("nonce_hash", name="uq_calendar_oauth_attempt_nonce"),
        )
        op.create_index("ix_calendar_oauth_attempts_user_id", "calendar_oauth_attempts", ["user_id"])
        op.create_index("ix_calendar_oauth_attempts_nonce_hash", "calendar_oauth_attempts", ["nonce_hash"], unique=True)
    if "prompt_versions" in _tables() and "change_note" not in _columns("prompt_versions"):
        op.add_column("prompt_versions", sa.Column("change_note", sa.String(500), nullable=True))
    if "seo_audit_runs" not in _tables():
        op.create_table(
            "seo_audit_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("target_url", sa.String(500), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_seo_audit_runs_created_at", "seo_audit_runs", ["created_at"])


def downgrade():
    # Non-destructive by policy: integration and prompt audit history is retained.
    pass
