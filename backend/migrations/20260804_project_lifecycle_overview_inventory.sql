BEGIN;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS onboarding_status VARCHAR(30) NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS onboarding_approved_by_user_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_projects_onboarding_approved_by_user_id'
    ) THEN
        ALTER TABLE projects
            ADD CONSTRAINT fk_projects_onboarding_approved_by_user_id
            FOREIGN KEY (onboarding_approved_by_user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

UPDATE projects p
SET onboarding_status = CASE
    WHEN COALESCE(pp.final_approved, FALSE) THEN 'completed'
    WHEN COALESCE(pp.completion_percentage, 0) = 100 THEN 'awaiting_confirmation'
    WHEN COALESCE(pp.completion_percentage, 0) > 0 THEN 'in_progress'
    ELSE 'draft'
END,
onboarding_completed_at = CASE
    WHEN COALESCE(pp.final_approved, FALSE) THEN COALESCE(pp.approved_for_sales_at, pp.updated_at)
    ELSE NULL
END
FROM project_profiles pp
WHERE pp.project_id = p.id;

CREATE INDEX IF NOT EXISTS ix_projects_onboarding_status ON projects(onboarding_status);

ALTER TABLE project_onboarding_sources
    ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS focal_point_x DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS focal_point_y DOUBLE PRECISION NOT NULL DEFAULT 0.5;

CREATE TABLE IF NOT EXISTS project_units (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id VARCHAR(36) REFERENCES project_onboarding_sources(id) ON DELETE SET NULL,
    unit_code VARCHAR(100) NOT NULL,
    typology VARCHAR(150),
    tower_or_phase VARCHAR(150),
    area NUMERIC(12, 2),
    bedrooms INTEGER,
    bathrooms INTEGER,
    list_price NUMERIC(16, 2),
    currency VARCHAR(10),
    status VARCHAR(30) NOT NULL DEFAULT 'available',
    inventory_updated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_project_units_project_code UNIQUE (project_id, unit_code)
);

CREATE INDEX IF NOT EXISTS ix_project_units_project_id ON project_units(project_id);
CREATE INDEX IF NOT EXISTS ix_project_units_status ON project_units(status);

COMMIT;
