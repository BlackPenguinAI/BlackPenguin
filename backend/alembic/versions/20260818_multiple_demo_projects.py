"""Allow a Company to own multiple versioned Demo Projects.

Revision ID: 20260818_multi_demo
Revises: 20260817_agent_simulation
"""

from alembic import op


revision = "20260818_multi_demo"
down_revision = "20260817_agent_simulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_projects_one_demo_per_company")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_demo_template_per_company "
        "ON projects (company_id, demo_template_version) "
        "WHERE is_demo = true AND demo_template_version IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_projects_demo_template_per_company")
    # Downgrade intentionally fails when a tenant now owns multiple Demo
    # Projects instead of deleting data to satisfy the legacy constraint.
    op.execute(
        "CREATE UNIQUE INDEX uq_projects_one_demo_per_company "
        "ON projects (company_id) WHERE is_demo = true"
    )
