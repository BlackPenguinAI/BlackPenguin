BEGIN;

ALTER TABLE onboarding_messages
  ADD COLUMN IF NOT EXISTS ui_payload JSONB,
  ADD COLUMN IF NOT EXISTS response_payload JSONB,
  ADD COLUMN IF NOT EXISTS in_reply_to_message_id VARCHAR(36);

ALTER TABLE project_messages
  ADD COLUMN IF NOT EXISTS ui_payload JSONB,
  ADD COLUMN IF NOT EXISTS response_payload JSONB,
  ADD COLUMN IF NOT EXISTS in_reply_to_message_id VARCHAR(36);

DO $$ BEGIN
  ALTER TABLE onboarding_messages
    ADD CONSTRAINT fk_onboarding_messages_reply
    FOREIGN KEY (in_reply_to_message_id) REFERENCES onboarding_messages(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE project_messages
    ADD CONSTRAINT fk_project_messages_reply
    FOREIGN KEY (in_reply_to_message_id) REFERENCES project_messages(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS ix_onboarding_messages_reply ON onboarding_messages(in_reply_to_message_id);
CREATE INDEX IF NOT EXISTS ix_project_messages_reply ON project_messages(in_reply_to_message_id);

CREATE TABLE IF NOT EXISTS onboarding_source_jobs (
  id VARCHAR(36) PRIMARY KEY,
  scope VARCHAR(20) NOT NULL,
  company_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36),
  source_id VARCHAR(36) NOT NULL,
  message_id VARCHAR(36),
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0,
  idempotency_key VARCHAR(64) NOT NULL,
  error_code VARCHAR(80),
  error_detail TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_onboarding_source_jobs_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_status ON onboarding_source_jobs(status);
CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_scope ON onboarding_source_jobs(scope);
CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_company ON onboarding_source_jobs(company_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_project ON onboarding_source_jobs(project_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_source_jobs_source ON onboarding_source_jobs(source_id);

COMMIT;
