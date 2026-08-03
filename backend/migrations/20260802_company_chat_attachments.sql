BEGIN;

ALTER TABLE company_onboarding_sources
    ADD COLUMN IF NOT EXISTS message_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS stored_filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS storage_path TEXT;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_company_onboarding_sources_message_id') THEN
        ALTER TABLE company_onboarding_sources ADD CONSTRAINT fk_company_onboarding_sources_message_id
            FOREIGN KEY (message_id) REFERENCES onboarding_messages(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_company_onboarding_sources_message_id ON company_onboarding_sources(message_id);
COMMIT;
