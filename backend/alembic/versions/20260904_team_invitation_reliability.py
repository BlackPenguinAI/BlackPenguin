"""Make Company user invitations idempotent.

Revision ID: 20260904_invite_reliability
Revises: 20260903_source_progress
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904_invite_reliability"
down_revision = "20260903_source_progress"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "idempotency_key" not in _columns("user_invitations"):
        op.add_column(
            "user_invitations",
            sa.Column("idempotency_key", sa.String(100), nullable=True),
        )
    if "ix_user_invitations_idempotency_key" not in _indexes("user_invitations"):
        op.create_index(
            "ix_user_invitations_idempotency_key",
            "user_invitations",
            ["idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    indexes = _indexes("user_invitations")
    if "ix_user_invitations_idempotency_key" in indexes:
        op.drop_index("ix_user_invitations_idempotency_key", table_name="user_invitations")
    if "idempotency_key" in _columns("user_invitations"):
        op.drop_column("user_invitations", "idempotency_key")
