"""Preserve immutable audit references when parent records are deleted.

Revision ID: 20261015_audit_refs
Revises: 20261014_company_timezone

Audit rows are append-only. Their former ``ON DELETE SET NULL`` foreign keys
made PostgreSQL update those rows while deleting a Company or user, which was
correctly rejected by the audit immutability trigger. The identifier columns
remain indexed historical values, but no longer participate in live referential
actions.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_audit_refs"
down_revision = "20261014_company_timezone"
branch_labels = None
depends_on = None


AUDIT_REFERENCES = (
    (
        "platform_audit_events",
        "platform_audit_events_company_id_fkey",
        "company_id",
        "companies",
    ),
    (
        "platform_audit_events",
        "platform_audit_events_actor_user_id_fkey",
        "actor_user_id",
        "users",
    ),
    (
        "data_export_audit_events",
        "data_export_audit_events_company_id_fkey",
        "company_id",
        "companies",
    ),
    (
        "data_export_audit_events",
        "data_export_audit_events_actor_user_id_fkey",
        "actor_user_id",
        "users",
    ),
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _foreign_keys(table: str) -> list[dict]:
    return sa.inspect(op.get_bind()).get_foreign_keys(table)


def _matching_constraint(table: str, column: str, referred_table: str) -> str | None:
    for foreign_key in _foreign_keys(table):
        if (
            foreign_key.get("constrained_columns") == [column]
            and foreign_key.get("referred_table") == referred_table
        ):
            return foreign_key.get("name")
    return None


def upgrade() -> None:
    tables = _tables()
    for table, _expected_name, column, referred_table in AUDIT_REFERENCES:
        if table not in tables:
            continue
        constraint_name = _matching_constraint(table, column, referred_table)
        if constraint_name:
            op.drop_constraint(constraint_name, table, type_="foreignkey")


def downgrade() -> None:
    tables = _tables()
    for table, constraint_name, column, referred_table in AUDIT_REFERENCES:
        if table not in tables:
            continue
        if _matching_constraint(table, column, referred_table) is None:
            op.create_foreign_key(
                constraint_name,
                table,
                referred_table,
                [column],
                ["id"],
                ondelete="SET NULL",
            )
