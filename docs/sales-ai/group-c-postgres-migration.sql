BEGIN;

-- Running upgrade 20261106_sales_dialogue -> 20261108_sales_visit_context

ALTER TABLE meetings ADD COLUMN visit_property_type_id VARCHAR(36);

ALTER TABLE meetings ADD COLUMN visit_unit_id VARCHAR(36);

ALTER TABLE meetings ADD COLUMN visit_context JSON;

ALTER TABLE meetings ADD CONSTRAINT fk_meetings_visit_property_type FOREIGN KEY(visit_property_type_id) REFERENCES project_property_types (id) ON DELETE SET NULL;

ALTER TABLE meetings ADD CONSTRAINT fk_meetings_visit_unit FOREIGN KEY(visit_unit_id) REFERENCES project_units (id) ON DELETE SET NULL;

UPDATE alembic_version SET version_num='20261108_sales_visit_context' WHERE alembic_version.version_num = '20261106_sales_dialogue';

COMMIT;

