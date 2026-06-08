from fastapi import FastAPI
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware
# Importamos todos los routers incluyendo los nuevos webhooks de la Semana 6
from app.api.v1 import auth, superadmin, projects, webhooks, leads

app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    description="API Core para la gestión Multi-tenant, ingesta omnicanal de leads y enrutamiento de IA en ventas inmobiliarias."
)

# Registrar el Middleware de Aislamiento Perimetral Multi-tenant
app.add_middleware(MultiTenantMiddleware)

# =================================================================
# RUTAS DE LA API (Con nombres estructurados y ordenados para Swagger UI)
# =================================================================

app.include_router(
    auth.router, 
    prefix=f"{settings.API_V1_STR}/auth", 
    tags=["1. Seguridad y Autenticación"]
)

app.include_router(
    superadmin.router, 
    prefix=f"{settings.API_V1_STR}/superadmin", 
    tags=["2. Gestión de Plataforma (SaaS Admin)"]
)

app.include_router(
    projects.router, 
    prefix=f"{settings.API_V1_STR}/projects", 
    tags=["3. Proyectos Inmobiliarios"]
)

# NUEVO: Conectamos el módulo de Ingesta Omnicanal y Webhooks (Semana 6)
app.include_router(
    webhooks.router, 
    prefix=f"{settings.API_V1_STR}/webhooks", 
    tags=["4. Ingesta de Leads y Webhooks"]
)

# NUEVO: Panel de control de Leads para el equipo comercial
app.include_router(
    leads.router, 
    prefix=f"{settings.API_V1_STR}/leads", 
    tags=["5. Gestión de Leads (Ventas)"]
)

@app.get("/", tags=["Sistema"])
def health_check():
    return {"status": "online", "environment": settings.ENVIRONMENT, "version": settings.VERSION}