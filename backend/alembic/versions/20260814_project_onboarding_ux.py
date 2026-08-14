"""Reconcile confirmed Project Profile names with the canonical Project.

Revision ID: 20260814_project_onboarding_ux
Revises: 20260814_project_sales_meta
"""
from alembic import op
import sqlalchemy as sa


revision = "20260814_project_onboarding_ux"
down_revision = "20260814_project_sales_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE projects AS project
        SET name = LEFT(BTRIM(profile.profile_data ->> 'project_name'), 150)
        FROM project_profiles AS profile
        WHERE profile.project_id = project.id
          AND NULLIF(BTRIM(profile.profile_data ->> 'project_name'), '') IS NOT NULL
          AND profile.field_states -> 'project_name' ->> 'status'
              IN ('confirmed', 'corrected_by_user')
          AND project.name IS DISTINCT FROM LEFT(BTRIM(profile.profile_data ->> 'project_name'), 150)
        """
    )
    op.execute(
        """
        UPDATE project_profiles
        SET profile_data = ((COALESCE(profile_data::jsonb, '{}'::jsonb) - 'sales_authorization'))::json,
            field_states = jsonb_set(
                COALESCE(field_states::jsonb, '{}'::jsonb),
                '{sales_authorization}',
                '{"status":"missing","applicable":true}'::jsonb,
                true
            )::json
        WHERE LOWER(COALESCE(profile_data ->> 'sales_authorization', ''))
              IN ('not yet authorized', 'human approval required per lead')
        """
    )
    op.execute(
        sa.text(
            "INSERT INTO schema_versions(version, applied_at) VALUES (:version, CURRENT_TIMESTAMP) "
            "ON CONFLICT (version) DO NOTHING"
        ).bindparams(version=revision)
    )


def downgrade() -> None:
    # Reverting a confirmed business name would discard user data, so only the
    # schema-version marker is removed.
    op.execute(sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision))
