"""Register durable onboarding jobs and structured message payloads.

Revision ID: 20260805_jobs_v2
Revises:
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260805_jobs_v2"
down_revision = None
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute(
            """
            ALTER TABLE IF EXISTS onboarding_messages
              ADD COLUMN IF NOT EXISTS ui_payload JSONB,
              ADD COLUMN IF NOT EXISTS response_payload JSONB,
              ADD COLUMN IF NOT EXISTS in_reply_to_message_id VARCHAR(36);
            ALTER TABLE IF EXISTS project_messages
              ADD COLUMN IF NOT EXISTS ui_payload JSONB,
              ADD COLUMN IF NOT EXISTS response_payload JSONB,
              ADD COLUMN IF NOT EXISTS in_reply_to_message_id VARCHAR(36);
            CREATE TABLE IF NOT EXISTS onboarding_source_jobs (
              id VARCHAR(36) PRIMARY KEY,
              scope VARCHAR(20) NOT NULL,
              company_id VARCHAR(36) NOT NULL,
              project_id VARCHAR(36),
              source_id VARCHAR(36) NOT NULL,
              message_id VARCHAR(36),
              status VARCHAR(20) NOT NULL DEFAULT 'queued',
              attempts INTEGER NOT NULL DEFAULT 0,
              idempotency_key VARCHAR(64) NOT NULL UNIQUE,
              error_code VARCHAR(80),
              error_detail TEXT,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              started_at TIMESTAMP,
              completed_at TIMESTAMP,
              available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_status ON onboarding_source_jobs(status);
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_scope ON onboarding_source_jobs(scope);
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_company ON onboarding_source_jobs(company_id);
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_project ON onboarding_source_jobs(project_id);
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_source ON onboarding_source_jobs(source_id);
            CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_available_at ON onboarding_source_jobs(available_at);
            CREATE TABLE IF NOT EXISTS schema_versions (
              version VARCHAR(100) PRIMARY KEY,
              applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_versions(version)
            VALUES ('20260805_onboarding_jobs_v2')
            ON CONFLICT (version) DO NOTHING;
            """
        )
        return

    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    for table in ("onboarding_messages", "project_messages"):
        if table not in tables:
            continue
        existing = _columns(table)
        with op.batch_alter_table(table) as batch:
            if "ui_payload" not in existing:
                batch.add_column(sa.Column("ui_payload", sa.JSON(), nullable=True))
            if "response_payload" not in existing:
                batch.add_column(sa.Column("response_payload", sa.JSON(), nullable=True))
            if "in_reply_to_message_id" not in existing:
                batch.add_column(sa.Column("in_reply_to_message_id", sa.String(36), nullable=True))

    if "onboarding_source_jobs" not in tables:
        op.create_table(
            "onboarding_source_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("scope", sa.String(20), nullable=False),
            sa.Column("company_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("source_id", sa.String(36), nullable=False),
            sa.Column("message_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    elif "available_at" not in _columns("onboarding_source_jobs"):
        op.add_column(
            "onboarding_source_jobs",
            sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    existing_indexes = {
        index["name"] for index in inspect(op.get_bind()).get_indexes("onboarding_source_jobs")
    }
    for name, columns in (
        ("ix_onboarding_source_jobs_status", ["status"]),
        ("ix_onboarding_source_jobs_scope", ["scope"]),
        ("ix_onboarding_source_jobs_company", ["company_id"]),
        ("ix_onboarding_source_jobs_project", ["project_id"]),
        ("ix_onboarding_source_jobs_source", ["source_id"]),
        ("ix_onboarding_source_jobs_available_at", ["available_at"]),
    ):
        if name not in existing_indexes:
            op.create_index(name, "onboarding_source_jobs", columns)

    if "schema_versions" not in set(inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "schema_versions",
            sa.Column("version", sa.String(100), primary_key=True),
            sa.Column("applied_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    op.execute(
        sa.text(
            "INSERT INTO schema_versions(version) VALUES (:version) "
            "ON CONFLICT (version) DO NOTHING"
        ).bindparams(version="20260805_onboarding_jobs_v2")
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(
            version="20260805_onboarding_jobs_v2"
        )
    )
