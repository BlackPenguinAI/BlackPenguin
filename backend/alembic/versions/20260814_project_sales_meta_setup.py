"""Add structured Project Sales routing and simulated Meta setup.

Revision ID: 20260814_project_sales_meta
Revises: 20260805_jobs_v2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260814_project_sales_meta"
down_revision = "20260805_jobs_v2"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "meta_connections" in tables:
        existing = _columns("meta_connections")
        with op.batch_alter_table("meta_connections") as batch:
            if "verification_mode" not in existing:
                batch.add_column(sa.Column("verification_mode", sa.String(20), nullable=False, server_default="real"))
            if "verification_status" not in existing:
                batch.add_column(sa.Column("verification_status", sa.String(30), nullable=False, server_default="pending"))
            if "verification_results" not in existing:
                batch.add_column(sa.Column("verification_results", sa.JSON(), nullable=False, server_default="{}"))
            if "page_access_confirmed" not in existing:
                batch.add_column(sa.Column("page_access_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "ad_account_access_confirmed" not in existing:
                batch.add_column(sa.Column("ad_account_access_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "leads_access_confirmed" not in existing:
                batch.add_column(sa.Column("leads_access_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "simulated_verified_at" not in existing:
                batch.add_column(sa.Column("simulated_verified_at", sa.DateTime(), nullable=True))
            batch.alter_column("token_ciphertext", existing_type=sa.Text(), nullable=True)
            batch.alter_column("token_hint", existing_type=sa.String(12), nullable=True)
        op.execute(
            "UPDATE meta_connections SET verification_status = 'succeeded', verification_mode = 'real' "
            "WHERE verified_at IS NOT NULL"
        )

    if "project_routing_states" not in tables:
        op.create_table(
            "project_routing_states",
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("policy", sa.String(30), nullable=False, server_default="round_robin"),
            sa.Column("last_assigned_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assignment_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    op.execute(
        sa.text(
            "INSERT INTO schema_versions(version, applied_at) VALUES (:version, CURRENT_TIMESTAMP) "
            "ON CONFLICT (version) DO NOTHING"
        ).bindparams(version="20260814_project_sales_meta")
    )


def downgrade() -> None:
    if "project_routing_states" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("project_routing_states")
    if "meta_connections" in set(inspect(op.get_bind()).get_table_names()):
        existing = _columns("meta_connections")
        with op.batch_alter_table("meta_connections") as batch:
            for column in (
                "simulated_verified_at", "leads_access_confirmed", "ad_account_access_confirmed",
                "page_access_confirmed", "verification_results", "verification_status", "verification_mode",
            ):
                if column in existing:
                    batch.drop_column(column)
    op.execute(sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision))
