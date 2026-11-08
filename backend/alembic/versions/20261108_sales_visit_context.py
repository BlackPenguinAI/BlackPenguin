"""Optional explicit visit references; leave all historical associations unknown."""
from alembic import op
import sqlalchemy as sa

revision='20261108_sales_visit_context'
down_revision='20261106_sales_dialogue'
branch_labels=None
depends_on=None


def upgrade():
    if op.get_bind().dialect.name=='sqlite':
        # Rebuilding meetings while foreign_keys=ON would cascade-delete visit
        # attachments. Nullable inline references can be added without copying.
        op.execute('ALTER TABLE meetings ADD COLUMN visit_property_type_id VARCHAR(36) REFERENCES project_property_types(id) ON DELETE SET NULL')
        op.execute('ALTER TABLE meetings ADD COLUMN visit_unit_id VARCHAR(36) REFERENCES project_units(id) ON DELETE SET NULL')
        op.execute('ALTER TABLE meetings ADD COLUMN visit_context JSON')
        return
    with op.batch_alter_table('meetings') as batch:
        batch.add_column(sa.Column('visit_property_type_id',sa.String(36),nullable=True))
        batch.add_column(sa.Column('visit_unit_id',sa.String(36),nullable=True))
        batch.add_column(sa.Column('visit_context',sa.JSON(),nullable=True))
        batch.create_foreign_key('fk_meetings_visit_property_type','project_property_types',['visit_property_type_id'],['id'],ondelete='SET NULL')
        batch.create_foreign_key('fk_meetings_visit_unit','project_units',['visit_unit_id'],['id'],ondelete='SET NULL')


def downgrade():
    if op.get_bind().dialect.name=='sqlite':
        op.execute('ALTER TABLE meetings DROP COLUMN visit_context')
        op.execute('ALTER TABLE meetings DROP COLUMN visit_unit_id')
        op.execute('ALTER TABLE meetings DROP COLUMN visit_property_type_id')
        return
    with op.batch_alter_table('meetings') as batch:
        batch.drop_constraint('fk_meetings_visit_unit',type_='foreignkey')
        batch.drop_constraint('fk_meetings_visit_property_type',type_='foreignkey')
        batch.drop_column('visit_context')
        batch.drop_column('visit_unit_id')
        batch.drop_column('visit_property_type_id')
