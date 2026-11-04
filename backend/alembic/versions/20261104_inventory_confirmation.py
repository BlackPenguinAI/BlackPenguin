"""Record who confirms inventory, without inventing historical confirmations."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_inventory_confirmation"
down_revision = "20261103_onboarding_versions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("project_property_types") as batch:
        batch.add_column(sa.Column("inventory_confirmed_by_user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_property_inventory_confirmer", "users", ["inventory_confirmed_by_user_id"], ["id"], ondelete="SET NULL")


def downgrade():
    with op.batch_alter_table("project_property_types") as batch:
        batch.drop_constraint("fk_property_inventory_confirmer", type_="foreignkey")
        batch.drop_column("inventory_confirmed_by_user_id")
