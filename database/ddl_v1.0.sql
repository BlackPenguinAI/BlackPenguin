-- =============================================================================
-- SCRIPT DE BASE DE DATOS: BLACK PENGUIN CORE (POSTGRESQL)
-- ESTADO: VERSIÓN ESTABLE RELACIONAL MULTI-TENANT
-- =============================================================================

-- 0. ELIMINACIÓN PREVENTIVA DE TABLAS (ORDEN CORRECTO DE DEPENDENCIAS)
DROP TABLE IF EXISTS llm_global_configs CASCADE;
DROP TABLE IF EXISTS appointments CASCADE;
DROP TABLE IF EXISTS leads CASCADE;
DROP TABLE IF EXISTS inventory_units CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS companies CASCADE;

-- ELIMINACIÓN DE TIPOS ENUMERADOS
DROP TYPE IF EXISTS appointment_status CASCADE;
DROP TYPE IF EXISTS funnel_stage CASCADE;
DROP TYPE IF EXISTS unit_status CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;

-- =============================================================================
-- 1. CREACIÓN DE TIPOS ENUMERADOS (ENUMS)
-- =============================================================================
CREATE TYPE user_role AS ENUM ('superadmin', 'admin', 'assistant', 'mkt', 'sales');
CREATE TYPE unit_status AS ENUM ('available', 'reserved', 'sold');
CREATE TYPE funnel_stage AS ENUM ('new', 'contacted', 'qualified', 'appointment_set', 'closed', 'lost');
CREATE TYPE appointment_status AS ENUM ('scheduled', 'completed', 'canceled');

-- =============================================================================
-- 2. CREACIÓN DE TABLAS TRANSACCIONALES Y MAESTRAS
-- =============================================================================

-- TABLA: companies (Tenants / Inquilinos)
CREATE TABLE companies (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    license_start TIMESTAMP WITH TIME ZONE NOT NULL,
    license_end TIMESTAMP WITH TIME ZONE NOT NULL,
    offline_payment_verified BOOLEAN DEFAULT FALSE NOT NULL,
    max_projects_allowed INTEGER DEFAULT 1 NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- TABLA: users (Usuarios, Credenciales y Roles)
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

-- TABLA: projects (Dataprints Inmobiliarios)
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

-- TABLA: inventory_units (Control de Stock de Unidades)
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

-- TABLA: leads (Prospectos y Calificación Predictiva)
CREATE TABLE leads (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL,
    project_id VARCHAR(36),
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    email VARCHAR(150),
    source VARCHAR(50) NOT NULL,
    intent_score NUMERIC(5, 2) DEFAULT 0.0 NOT NULL,
    is_opt_out BOOLEAN DEFAULT FALSE NOT NULL,
    funnel_stage funnel_stage DEFAULT 'new' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_lead_company FOREIGN KEY (company_id) 
        REFERENCES companies(id) ON DELETE CASCADE,
    CONSTRAINT fk_lead_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL
);

-- TABLA: appointments (Mapeo de Citas y Handoff Humano)
CREATE TABLE appointments (
    id VARCHAR(36) PRIMARY KEY,
    lead_id VARCHAR(36) NOT NULL,
    sales_user_id VARCHAR(36) NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    google_event_id VARCHAR(255) NOT NULL,
    status appointment_status DEFAULT 'scheduled' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_appointment_lead FOREIGN KEY (lead_id) 
        REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_appointment_sales FOREIGN KEY (sales_user_id) 
        REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_google_event_id UNIQUE (google_event_id)
);

-- TABLA: llm_global_configs (Consola de Control del LLM Gateway Agnóstico)
CREATE TABLE llm_global_configs (
    id VARCHAR(36) PRIMARY KEY,
    active_provider VARCHAR(50) NOT NULL,
    active_model VARCHAR(100) NOT NULL,
    master_system_prompt TEXT NOT NULL,
    updated_by VARCHAR(36),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_config_user FOREIGN KEY (updated_by) 
        REFERENCES users(id) ON DELETE SET NULL
);

-- =============================================================================
-- 3. CREACIÓN DE ÍNDICES PARA OPTIMIZACIÓN MULTI-TENANT (RENDIMIENTO)
-- =============================================================================
-- Estos índices evitan que las consultas de una empresa busquen en datos de otra.
CREATE INDEX idx_users_company_id ON users(company_id);
CREATE INDEX idx_projects_company_id ON projects(company_id);
CREATE INDEX idx_leads_company_id ON leads(company_id);
CREATE INDEX idx_leads_phone ON leads(phone);
CREATE INDEX idx_inventory_project_id ON inventory_units(project_id);
CREATE INDEX idx_appointments_lead_id ON appointments(lead_id);
CREATE INDEX idx_appointments_sales_user ON appointments(sales_user_id);

-- =============================================================================
-- 4. AUTOMATIZACIÓN: TRIGGER PARA ACTUALIZAR EL CAMPO 'updated_at'
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_inventory_units_updated_at
BEFORE UPDATE ON inventory_units
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
