from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware

# =================================================================
# 🚀 IMPORTACIÓN DE MICRO-MÓDULOS PLANOS (DDD - 100% POSTGRESQL)
# =================================================================
from app.modules.auth.router import router as auth_router
from app.modules.waitlist.router import router as waitlist_router
from app.modules.subscriptions.router import router as subscriptions_router
from app.modules.companies.router import router as companies_router
from app.modules.users.router import router as users_router
from app.modules.system_settings.router import router as system_settings_router
from app.modules.ai_core.router import router as ai_core_router
from app.modules.company_onboarding.router import router as company_onboarding_router
from app.modules.projects.router import router as projects_router
from app.modules.brokers.router import router as brokers_router
from app.modules.sales_crm.router import router as sales_crm_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.dashboard.legacy_router import router as legacy_dashboard_router
from app.modules.health.router import router as health_router
from app.modules.project_team.router import router as project_team_router
from app.modules.sales_agent.router import router as sales_agent_router
from app.modules.meta_leads.router import router as meta_leads_router

from sqlalchemy import text
from app.db.postgres import engine

app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    description="Black Penguin Core API v2 - DDD Flat Architecture.",
)

# 🚀 CONFIGURACIÓN DE CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",         
        "https://blackpenguin.ai",       
        "https://www.blackpenguin.ai"    
    ], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# 🚀 MIDDLEWARE MULTI-TENANT
app.add_middleware(MultiTenantMiddleware)

# =================================================================
# REGISTRO DE RUTAS POR MICRO-MÓDULO
# =================================================================

# 1. Autenticación y Captación Pública
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["1. Autenticación"])
app.include_router(waitlist_router, prefix=f"{settings.API_V1_STR}/waitlist", tags=["2. Waitlist"])

# 2. Gestión de Suscripciones y Clientes Corporativos
app.include_router(subscriptions_router, prefix=f"{settings.API_V1_STR}/plans", tags=["3. Suscripciones"])
app.include_router(companies_router, prefix=f"{settings.API_V1_STR}/companies", tags=["4. Compañías"])
app.include_router(users_router, prefix=f"{settings.API_V1_STR}/users", tags=["5. Usuarios"])

# 3. Configuraciones e Infraestructura de IA
app.include_router(system_settings_router, prefix=f"{settings.API_V1_STR}/system", tags=["6. Configuración Sistema"])
app.include_router(ai_core_router, prefix=f"{settings.API_V1_STR}/ai", tags=["7. Motor de IA"])

# 4. Onboarding y Core Inmobiliario
app.include_router(company_onboarding_router, prefix=f"{settings.API_V1_STR}/company-onboarding", tags=["8. Onboarding Empresa"])
app.include_router(projects_router, prefix=f"{settings.API_V1_STR}/projects", tags=["9. Proyectos Inmobiliarios"])
app.include_router(brokers_router, prefix=f"{settings.API_V1_STR}/brokers", tags=["10. Brokers"])

# 5. CRM, Agente de Ventas y Citas
app.include_router(sales_crm_router, prefix=f"{settings.API_V1_STR}/sales", tags=["11. CRM & Ventas"])
app.include_router(dashboard_router, prefix=f"{settings.API_V1_STR}/dashboard", tags=["12. Dashboard"])
app.include_router(legacy_dashboard_router, prefix=f"{settings.API_V1_STR}/tenants", tags=["12. Dashboard"])
app.include_router(health_router, prefix=f"{settings.API_V1_STR}/health", tags=["Health"])
app.include_router(project_team_router, prefix=f"{settings.API_V1_STR}/projects", tags=["Project Team & Routing"])
app.include_router(sales_agent_router, prefix=f"{settings.API_V1_STR}/sales-agent", tags=["Sales Agent"])
app.include_router(meta_leads_router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["Meta Lead Ads"])

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Black Penguin API v2 (DDD PostgreSQL) is operational."}

# Inyectamos el reparador en el evento de inicio del servidor
@app.on_event("startup")
def fix_database_schema():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            print("✅ EXCELENTE: Columna 'created_at' inyectada forzosamente en PostgreSQL")
        except Exception as e:
            pass
