"""Firebase identities and invitation lifecycle.

Revision ID: 20260901_firebase_identity
Revises: 20260831_platform_experience
"""

from alembic import op
import sqlalchemy as sa

revision = "20260901_firebase_identity"
down_revision = "20260831_platform_experience"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    columns = _columns("users")
    if "firebase_uid" not in columns:
        op.add_column("users", sa.Column("firebase_uid", sa.String(128), nullable=True))
        op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)
    if "auth_status" not in columns:
        auth_status = sa.Enum(
            "INVITED", "ACTIVE", "SUSPENDED", "PROVISIONING_FAILED", "MIGRATION_REQUIRED",
            name="userauthstatus",
        )
        auth_status.create(op.get_bind(), checkfirst=True)
        op.add_column("users", sa.Column("auth_status", auth_status, nullable=False, server_default="ACTIVE"))
    for name in ("invitation_sent_at", "activated_at", "last_login_at"):
        if name not in columns:
            op.add_column("users", sa.Column(name, sa.DateTime(), nullable=True))

    if "user_invitations" not in _tables():
        op.create_table(
            "user_invitations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("invited_by_user_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_user_invitations_user_id", "user_invitations", ["user_id"])
        op.create_index("ix_user_invitations_status", "user_invitations", ["status"])

    firebase_columns = _columns("firebase_configurations")
    additions = {
        "service_account_ciphertext": sa.Column("service_account_ciphertext", sa.Text(), nullable=True),
        "service_account_hint": sa.Column("service_account_hint", sa.String(255), nullable=True),
        "is_enabled": sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        "verification_status": sa.Column("verification_status", sa.String(30), nullable=False, server_default="not_configured"),
        "verified_at": sa.Column("verified_at", sa.DateTime(), nullable=True),
        "last_error": sa.Column("last_error", sa.Text(), nullable=True),
        "auth_mode": sa.Column("auth_mode", sa.String(20), nullable=False, server_default="hybrid"),
        "action_handler_url": sa.Column("action_handler_url", sa.String(500), nullable=False, server_default="https://blackpenguin.ai/activate-account"),
    }
    for name, column in additions.items():
        if name not in firebase_columns:
            op.add_column("firebase_configurations", column)


def downgrade():
    # Non-destructive by policy: identities and invitation audit history remain.
    pass
