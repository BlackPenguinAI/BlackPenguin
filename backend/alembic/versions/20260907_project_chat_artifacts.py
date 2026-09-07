"""Persist structured receipts in Project onboarding chat.

Revision ID: 20260907_project_receipts
Revises: 20260907_meta_oauth_media
"""

from alembic import op
import sqlalchemy as sa


revision = "20260907_project_receipts"
down_revision = "20260907_meta_oauth_media"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "artifact_payload" not in _columns("project_messages"):
        op.add_column("project_messages", sa.Column("artifact_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "artifact_payload" in _columns("project_messages"):
        op.drop_column("project_messages", "artifact_payload")
