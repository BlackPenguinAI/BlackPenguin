-- =============================================================================
-- SCRIPT DE BASE DE DATOS: BLACK PENGUIN CORE (POSTGRESQL)
-- VERSION: PERSISTENCIA v2.0 (ESQUEMA COMERCIAL Y MULTI-LLM ADAPTADO)
-- ENVIRONMENT: DIGITALOCEAN DROPLETS / PRODUCTION K3S CLUSTER
-- =============================================================================

-- 0. ELIMINACIÓN DE SEGURIDAD EN CASCADA (EVITAR CONFLICTOS DE DEPLOYMENT)
DROP TABLE IF EXISTS llm_global_configs CASCADE;
DROP TABLE IF EXISTS appointments CASCADE;
DROP TABLE IF EXISTS leads CASCADE;
DROP TABLE IF EXISTS inventory_units CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS company_specialized_agents CASCADE;
DROP TABLE IF EXISTS companies CASCADE;

-- ELIMINACIÓN DE TIPOS ENUMERADOS ASOCIADOS
DROP TYPE IF EXISTS appointment_status CASCADE;
DROP TYPE IF EXISTS funnel_stage CASCADE;
DROP TYPE IF EXISTS unit_status CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;
DROP TYPE IF EXISTS specialized_agent_type CASCADE;
DROP TYPE IF EXISTS plan_tier CASCADE;

-- =============================================================================
-- 1. CREACIÓN DE TIPOS ENUMERADOS DE NEGOCIO Y OPERACIÓN
-- =============================================================================
CREATE TYPE plan_tier AS ENUM ('core', 'enterprise');
CREATE TYPE specialized_agent_type AS ENUM ('leasing', 'investor', 'retention', 'financing');
CREATE TYPE user_role AS ENUM ('superadmin', 'admin', 'assistant', 'mkt', 'sales');
CREATE TYPE unit_status AS ENUM ('available', 'reserved', 'sold');
CREATE TYPE funnel_stage AS ENUM ('new', 'contacted', 'qualified', 'appointment_set', 'closed', 'lost');
CREATE TYPE appointment_status AS ENUM ('scheduled', 'completed', 'canceled');

-- =============================================================================
-- 2. CREACIÓN DE TABLAS ESTRUCTURALES (TENANCY, USUARIOS Y CONTROL COMERCIAL)
-- =============================================================================

-- TABLA: companies (Tenants / Inquilinos SaaS)
CREATE TABLE companies (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    license_start TIMESTAMP WITH TIME ZONE NOT NULL,
    license_end TIMESTAMP WITH TIME ZONE NOT NULL,
    plan_tier plan_tier DEFAULT 'core' NOT NULL,
    max_projects_allowed INTEGER DEFAULT 1 NOT NULL,
    has_voice_agents BOOLEAN DEFAULT FALSE NOT NULL,
    has_property_tour BOOLEAN DEFAULT FALSE NOT NULL,
    has_enterprise_integrations BOOLEAN DEFAULT FALSE NOT NULL,
    voice_minutes_allowance INTEGER DEFAULT 0 NOT NULL,
    offline_payment_verified BOOLEAN DEFAULT FALSE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- TABLA: company_specialized_agents (Add-ons de IA Especializados Adquiridos)
CREATE TABLE company_specialized_agents (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL,
    agent_type specialized_agent_type NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_specialized_agent_company FOREIGN KEY (company_id) 
        REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT uq_company_agent_type UNIQUE (company_id, agent_type)
);

-- TABLA: users (Usuarios Operativos y Control de Acceso RBAC)
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36),
    email VARCHAR(150) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role user_role NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    google_oauth_token TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_user_company FOREIGN KEY (company_id) 
        REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_email UNIQUE (email)
);

-- =============================================================================
-- 3. CREACIÓN DE TABLAS INMOBILIARIAS (CONOCIMIENTO Y CONTROL DE STOCK)
-- =============================================================================

-- TABLA: projects (Dataprints de Desarrollos Inmobiliarios)
CREATE TABLE projects (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL,
    name VARCHAR(150) NOT NULL,
    location VARCHAR(255) NOT NULL,
    base_price NUMERIC(15, 2) NOT NULL,
    amenities TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_project_company FOREIGN KEY (company_id) 
        REFERENCES companies(id) ON DELETE CASCADE
);

-- TABLA: inventory_units (Control de Stock Fino e Inventario Real)
CREATE TABLE inventory_units (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL,
    unit_number VARCHAR(50) NOT NULL,
    typology VARCHAR(100) NOT NULL,
    price NUMERIC(15, 2) NOT NULL,
    status unit_status DEFAULT 'available' NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_unit_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE
);

-- =============================================================================
-- 4. CREACIÓN DE TABLAS DE CONVERSIÓN (EMBUDO, CITAS Y GATEWAY COGNITIVO)
-- =============================================================================

-- TABLA: leads (Prospectos Unificados e Intent Scoring Predictivo)
CREATE TABLE leads (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36),
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    email VARCHAR(150),
    source VARCHAR(50) NOT NULL, -- meta_ads, google_ads, landing_page, voice_call
    intent_score NUMERIC(5, 2) DEFAULT 0.0 NOT NULL,
    is_opt_out BOOLEAN DEFAULT FALSE NOT NULL,
    funnel_stage funnel_stage DEFAULT 'new' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_lead_company FOREIGN KEY (company_id) 
        REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT fk_lead_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL
);

-- TABLA: appointments (Mapeo de Reservas y Sincronización Google Calendar)
CREATE TABLE appointments (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL,
    sales_user_id VARCHAR(36) NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    google_event_id VARCHAR(255) NOT NULL,
    booking_channel VARCHAR(50) DEFAULT 'chat_bot' NOT NULL, -- chat_bot, voice_agent
    status appointment_status DEFAULT 'scheduled' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_appointment_lead FOREIGN KEY (lead_id) 
        REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_appointment_sales FOREIGN KEY (sales_user_id) 
        REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_google_event_id UNIQUE (google_event_id)
);

-- TABLA: llm_global_configs (Consola de Control y Balanceo Multi-LLM en Caliente)
CREATE TABLE llm_global_configs (
    id VARCHAR(36) PRIMARY KEY,
    active_provider VARCHAR(50) NOT NULL, -- openai, deepseek, anthropic
    active_model VARCHAR(100) NOT NULL,  -- gpt-4o, deepseek-chat, claude-3-5-sonnet
    master_system_prompt TEXT NOT NULL,
    updated_by VARCHAR(36),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_config_user FOREIGN KEY (updated_by) 
        REFERENCES users(id) ON DELETE SET NULL
);

-- =============================================================================
-- 5. ÍNDICES DE OPTIMIZACIÓN MULTI-TENANT (GARANTÍA DE PERFORMANCE)
-- =============================================================================
-- Evitan colisiones de búsquedas indexando por la partición lógica 'company_id'.
CREATE INDEX idx_v2_companies_tier ON companies(plan_tier);
CREATE INDEX idx_v2_specialized_agents_company ON company_specialized_agents(company_id);
CREATE INDEX idx_v2_users_company_id ON users(company_id);
CREATE INDEX idx_v2_projects_company_id ON projects(company_id);
CREATE INDEX idx_v2_inventory_project_id ON inventory_units(project_id);
CREATE INDEX idx_v2_leads_company_id ON leads(company_id);
CREATE INDEX idx_v2_leads_phone_search ON leads(phone);
CREATE INDEX idx_v2_appointments_sales_user ON appointments(sales_user_id);

-- =============================================================================
-- 6. AUTOMATIZACIÓN DE TIEMPOS DE ACTUALIZACIÓN (AUDITORÍA DE STOCK)
-- =============================================================================
CREATE OR REPLACE FUNCTION update_inventory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_v2_update_inventory_units_timestamp
BEFORE UPDATE ON inventory_units
FOR EACH ROW
EXECUTE FUNCTION update_inventory_timestamp();
