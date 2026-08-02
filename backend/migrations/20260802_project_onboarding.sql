BEGIN;

ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS profile_data JSON NOT NULL DEFAULT '{}';
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS field_states JSON NOT NULL DEFAULT '{}';
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS field_sources JSON NOT NULL DEFAULT '{}';
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS completion_percentage INTEGER NOT NULL DEFAULT 0;
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS final_approved BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS sales_activation_status VARCHAR(30) NOT NULL DEFAULT 'not_ready';
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS inventory_last_updated_at TIMESTAMP;
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS approved_for_sales_at TIMESTAMP;
ALTER TABLE project_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_projects_company_id ON projects(company_id);

DO $$ BEGIN
    CREATE TYPE projectsourcekind AS ENUM ('URL', 'UPLOADED_FILE', 'IMAGE', 'SPREADSHEET');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE projectsourcestatus AS ENUM ('PROCESSING', 'READY', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE projectproposalstatus AS ENUM ('PENDING', 'CONFIRMED', 'CORRECTED', 'REJECTED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS project_onboarding_sources (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uploaded_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    kind projectsourcekind NOT NULL,
    status projectsourcestatus NOT NULL DEFAULT 'PROCESSING',
    name VARCHAR(255) NOT NULL,
    url TEXT,
    mime_type VARCHAR(150),
    size_bytes INTEGER,
    sha256 VARCHAR(64),
    extracted_text TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_project_onboarding_sources_project_id ON project_onboarding_sources(project_id);
CREATE INDEX IF NOT EXISTS ix_project_onboarding_sources_sha256 ON project_onboarding_sources(sha256);

CREATE TABLE IF NOT EXISTS project_onboarding_proposals (
    id VARCHAR(36) PRIMARY KEY,
    source_id VARCHAR(36) NOT NULL REFERENCES project_onboarding_sources(id) ON DELETE CASCADE,
    field_key VARCHAR(100) NOT NULL,
    value JSON,
    evidence TEXT,
    confidence VARCHAR(20),
    status projectproposalstatus NOT NULL DEFAULT 'PENDING',
    reviewed_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_project_onboarding_proposals_source_id ON project_onboarding_proposals(source_id);

CREATE TABLE IF NOT EXISTS meta_connections (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    label VARCHAR(120) NOT NULL,
    business_account_id VARCHAR(150),
    ad_account_id VARCHAR(150),
    page_id VARCHAR(150),
    token_ciphertext TEXT NOT NULL,
    token_hint VARCHAR(12) NOT NULL,
    scopes JSON NOT NULL DEFAULT '[]',
    expires_at TIMESTAMP,
    verified_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_meta_connections_company_id ON meta_connections(company_id);

CREATE TABLE IF NOT EXISTS project_campaigns (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    meta_connection_id VARCHAR(36) REFERENCES meta_connections(id) ON DELETE SET NULL,
    name VARCHAR(180) NOT NULL,
    platform VARCHAR(30) NOT NULL DEFAULT 'meta',
    objective VARCHAR(100),
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    external_campaign_id VARCHAR(150),
    lead_form_id VARCHAR(150),
    audience_notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_project_campaigns_project_id ON project_campaigns(project_id);

COMMIT;
