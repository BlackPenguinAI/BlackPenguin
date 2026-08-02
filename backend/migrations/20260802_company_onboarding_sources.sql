BEGIN;

DO $$ BEGIN
    CREATE TYPE sourcekind AS ENUM (
        'OFFICIAL_WEBSITE', 'SOCIAL_PROFILE', 'ONLINE_DOCUMENT',
        'THIRD_PARTY', 'UPLOADED_FILE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE sourcestatus AS ENUM ('PROCESSING', 'READY', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE proposalstatus AS ENUM ('PENDING', 'CONFIRMED', 'CORRECTED', 'REJECTED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS company_onboarding_sources (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    uploaded_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    kind sourcekind NOT NULL,
    status sourcestatus NOT NULL DEFAULT 'PROCESSING',
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

CREATE INDEX IF NOT EXISTS ix_company_onboarding_sources_company_id
    ON company_onboarding_sources(company_id);
CREATE INDEX IF NOT EXISTS ix_company_onboarding_sources_sha256
    ON company_onboarding_sources(sha256);

CREATE TABLE IF NOT EXISTS company_onboarding_proposals (
    id VARCHAR(36) PRIMARY KEY,
    source_id VARCHAR(36) NOT NULL REFERENCES company_onboarding_sources(id) ON DELETE CASCADE,
    field_key VARCHAR(100) NOT NULL,
    value JSON,
    evidence TEXT,
    confidence VARCHAR(20),
    status proposalstatus NOT NULL DEFAULT 'PENDING',
    reviewed_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_company_onboarding_proposals_source_id
    ON company_onboarding_proposals(source_id);

COMMIT;
