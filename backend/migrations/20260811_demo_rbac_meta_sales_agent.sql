BEGIN;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS demo_template_version VARCHAR(30);
CREATE INDEX IF NOT EXISTS ix_projects_is_demo ON projects (is_demo);
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_one_demo_per_company ON projects (company_id) WHERE is_demo = TRUE;

ALTER TABLE leads ADD COLUMN IF NOT EXISTS campaign_id VARCHAR(36) REFERENCES project_campaigns(id) ON DELETE SET NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS assigned_sales_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS platform VARCHAR(30) NOT NULL DEFAULT 'manual';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS external_lead_id VARCHAR(180);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS preferred_channel VARCHAR(30);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS channel_address VARCHAR(180);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS consent_status VARCHAR(30) NOT NULL DEFAULT 'unknown';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS consent_captured_at TIMESTAMP;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS qualification_summary TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS agent_status VARCHAR(30) NOT NULL DEFAULT 'paused';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMP;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS stage_changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_action_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS ix_leads_campaign_id ON leads (campaign_id);
CREATE INDEX IF NOT EXISTS ix_leads_assigned_sales_user_id ON leads (assigned_sales_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_platform_external_id
    ON leads (platform, external_lead_id) WHERE external_lead_id IS NOT NULL;

DO $$ BEGIN
    ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS 'confirmed';
    ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS 'no_show';
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS assigned_sales_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 45;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS modality VARCHAR(30) NOT NULL DEFAULT 'virtual';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR(30) NOT NULL DEFAULT 'pending';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS calendar_sync_status VARCHAR(30) NOT NULL DEFAULT 'not_connected';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_url TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS notes TEXT;
CREATE INDEX IF NOT EXISTS ix_meetings_assigned_sales_user_id ON meetings (assigned_sales_user_id);

CREATE TABLE IF NOT EXISTS project_user_assignments (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    responsibility VARCHAR(30) NOT NULL CHECK (responsibility IN ('marketing', 'sales')),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    routing_weight INTEGER NOT NULL DEFAULT 100 CHECK (routing_weight BETWEEN 0 AND 1000),
    accepts_new_leads BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_project_user_assignment UNIQUE (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_project_user_assignments_project_id ON project_user_assignments(project_id);
CREATE INDEX IF NOT EXISTS ix_project_user_assignments_user_id ON project_user_assignments(user_id);

CREATE TABLE IF NOT EXISTS lead_stage_history (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    from_stage VARCHAR(40),
    to_stage VARCHAR(40) NOT NULL,
    actor_type VARCHAR(30) NOT NULL,
    actor_id VARCHAR(36),
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_lead_stage_history_lead_id ON lead_stage_history(lead_id);

CREATE TABLE IF NOT EXISTS sales_conversations (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id VARCHAR(36) REFERENCES project_campaigns(id) ON DELETE SET NULL,
    lead_id VARCHAR(36) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    stage VARCHAR(40) NOT NULL DEFAULT 'new',
    automation_level INTEGER NOT NULL DEFAULT 0 CHECK (automation_level BETWEEN 0 AND 3),
    is_paused BOOLEAN NOT NULL DEFAULT TRUE,
    pause_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sales_conversation_lead_channel UNIQUE (lead_id, channel)
);
CREATE INDEX IF NOT EXISTS ix_sales_conversations_company_id ON sales_conversations(company_id);
CREATE INDEX IF NOT EXISTS ix_sales_conversations_project_id ON sales_conversations(project_id);
CREATE INDEX IF NOT EXISTS ix_sales_conversations_campaign_id ON sales_conversations(campaign_id);
CREATE INDEX IF NOT EXISTS ix_sales_conversations_lead_id ON sales_conversations(lead_id);

CREATE TABLE IF NOT EXISTS sales_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES sales_conversations(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    provider_message_id VARCHAR(180),
    status VARCHAR(30) NOT NULL DEFAULT 'received',
    metadata_json JSON NOT NULL DEFAULT '{}'::json,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sales_message_provider_id UNIQUE (channel, provider_message_id)
);
CREATE INDEX IF NOT EXISTS ix_sales_messages_conversation_id ON sales_messages(conversation_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES sales_conversations(id) ON DELETE CASCADE,
    event_id VARCHAR(180) NOT NULL UNIQUE,
    mode VARCHAR(20) NOT NULL DEFAULT 'simulation',
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    graph_version VARCHAR(30) NOT NULL,
    toolset_version VARCHAR(30) NOT NULL,
    prompt_configuration_id VARCHAR(36),
    prompt_snapshot JSON NOT NULL,
    model VARCHAR(180) NOT NULL,
    input_snapshot JSON NOT NULL DEFAULT '{}'::json,
    output_snapshot JSON NOT NULL DEFAULT '{}'::json,
    token_usage JSON NOT NULL DEFAULT '{}'::json,
    estimated_cost_usd VARCHAR(30),
    error_code VARCHAR(80),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_conversation_id ON agent_runs(conversation_id);

CREATE TABLE IF NOT EXISTS outbound_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES sales_conversations(id) ON DELETE CASCADE,
    agent_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    idempotency_key VARCHAR(220) NOT NULL UNIQUE,
    channel VARCHAR(30) NOT NULL,
    recipient VARCHAR(180),
    content TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    approved_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP,
    sent_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_outbound_messages_conversation_id ON outbound_messages(conversation_id);
CREATE INDEX IF NOT EXISTS ix_outbound_messages_agent_run_id ON outbound_messages(agent_run_id);
CREATE INDEX IF NOT EXISTS ix_outbound_messages_status ON outbound_messages(status);

CREATE TABLE IF NOT EXISTS external_webhook_events (
    id VARCHAR(36) PRIMARY KEY,
    platform VARCHAR(30) NOT NULL,
    external_event_id VARCHAR(180) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'received',
    error_message TEXT,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    CONSTRAINT uq_webhook_platform_event UNIQUE (platform, external_event_id)
);

CREATE TABLE IF NOT EXISTS calendar_connections (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(30) NOT NULL,
    calendar_id VARCHAR(255),
    access_token_ciphertext TEXT NOT NULL,
    refresh_token_ciphertext TEXT,
    token_expires_at TIMESTAMP,
    scopes JSON NOT NULL DEFAULT '[]'::json,
    sync_token TEXT,
    watch_channel_id VARCHAR(255),
    watch_resource_id VARCHAR(255),
    watch_expires_at TIMESTAMP,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    last_synced_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_calendar_connection_user_provider UNIQUE (user_id, provider)
);

COMMIT;
