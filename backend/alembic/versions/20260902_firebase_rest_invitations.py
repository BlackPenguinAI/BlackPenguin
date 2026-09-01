"""Firebase REST invitation retries.

Revision ID: 20260902_firebase_rest
Revises: 20260901_firebase_identity
"""

from alembic import op
import sqlalchemy as sa

revision = "20260902_firebase_rest"
down_revision = "20260901_firebase_identity"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns("user_invitations")
    if "last_attempt_at" not in columns:
        op.add_column("user_invitations", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
    if "provisioning_secret_ciphertext" not in columns:
        op.add_column(
            "user_invitations",
            sa.Column("provisioning_secret_ciphertext", sa.String(500), nullable=True),
        )
    op.execute("UPDATE firebase_configurations SET auth_mode = 'rest'")


def downgrade() -> None:
    # Non-destructive: retry audit data and encrypted reconciliation material remain.
    pass
