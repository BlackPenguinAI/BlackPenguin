"""Add onboarding media evidence and Meta OAuth foundations.

Revision ID: 20260907_meta_oauth_media
Revises: 20260905_meta_live_sms
"""

from alembic import op
import sqlalchemy as sa


revision = "20260907_meta_oauth_media"
down_revision = "20260905_meta_live_sms"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "media_evidence" not in _columns("onboarding_messages"):
        op.add_column("onboarding_messages", sa.Column("media_evidence", sa.JSON(), nullable=True))
    if "media_evidence" not in _columns("project_messages"):
        op.add_column("project_messages", sa.Column("media_evidence", sa.JSON(), nullable=True))
    if "meta_platform_configurations" not in _tables():
        op.create_table(
            "meta_platform_configurations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("app_id", sa.String(100), nullable=True),
            sa.Column("app_secret_ciphertext", sa.Text(), nullable=True),
            sa.Column("app_secret_hint", sa.String(12), nullable=True),
            sa.Column("login_config_id", sa.String(150), nullable=True),
            sa.Column("graph_api_version", sa.String(20), nullable=False, server_default="v20.0"),
            sa.Column("redirect_uri", sa.String(500), nullable=False),
            sa.Column("webhook_callback_url", sa.String(500), nullable=False),
            sa.Column("webhook_verify_token_ciphertext", sa.Text(), nullable=True),
            sa.Column("webhook_verify_token_hint", sa.String(12), nullable=True),
            sa.Column("requested_scopes", sa.JSON(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"),
            sa.Column("app_review_status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("business_verification_status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "meta_oauth_attempts" not in _tables():
        op.create_table(
            "meta_oauth_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("nonce_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_meta_oauth_attempts_user_id", "meta_oauth_attempts", ["user_id"])
        op.create_index("ix_meta_oauth_attempts_company_id", "meta_oauth_attempts", ["company_id"])
        op.create_index("ix_meta_oauth_attempts_project_id", "meta_oauth_attempts", ["project_id"])
        op.create_index("ix_meta_oauth_attempts_nonce_hash", "meta_oauth_attempts", ["nonce_hash"], unique=True)
    if "meta_authorizations" not in _tables():
        op.create_table(
            "meta_authorizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connected_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("meta_user_id", sa.String(150), nullable=False),
            sa.Column("meta_user_name", sa.String(255), nullable=True),
            sa.Column("token_ciphertext", sa.Text(), nullable=False),
            sa.Column("token_hint", sa.String(12), nullable=True),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("verification_results", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("company_id", "meta_user_id", name="uq_meta_authorization_company_user"),
        )
        op.create_index("ix_meta_authorizations_company_id", "meta_authorizations", ["company_id"])
    if "authorization_id" not in _columns("meta_connections"):
        op.add_column("meta_connections", sa.Column("authorization_id", sa.String(36), nullable=True))
        op.create_foreign_key("fk_meta_connections_authorization_id", "meta_connections", "meta_authorizations", ["authorization_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_meta_connections_authorization_id", "meta_connections", ["authorization_id"])


def downgrade() -> None:
    if "authorization_id" in _columns("meta_connections"):
        op.drop_index("ix_meta_connections_authorization_id", table_name="meta_connections")
        op.drop_constraint("fk_meta_connections_authorization_id", "meta_connections", type_="foreignkey")
        op.drop_column("meta_connections", "authorization_id")
    if "meta_authorizations" in _tables():
        op.drop_table("meta_authorizations")
    if "meta_oauth_attempts" in _tables():
        op.drop_table("meta_oauth_attempts")
    if "meta_platform_configurations" in _tables():
        op.drop_table("meta_platform_configurations")
    if "media_evidence" in _columns("project_messages"):
        op.drop_column("project_messages", "media_evidence")
    if "media_evidence" in _columns("onboarding_messages"):
        op.drop_column("onboarding_messages", "media_evidence")
