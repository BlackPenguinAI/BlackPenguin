from fastapi import FastAPI
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware
# 1. Importamos el nuevo archivo 'projects'
from app.api.v1 import auth, superadmin, projects

app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    description="API Core para la gestión Multi-tenant y enrutamiento de IA en ventas inmobiliarias."
)

# Registrar el Middleware de Aislamiento Perimetral
app.add_middleware(MultiTenantMiddleware)

# =================================================================
# RUTAS DE LA API (Con nombres profesionales para Swagger UI)
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

# 2. NUEVO: Conectamos el módulo de Proyectos Inmobiliarios
app.include_router(
    projects.router, 
    prefix=f"{settings.API_V1_STR}/projects", 
    tags=["3. Proyectos Inmobiliarios"]
)

@app.get("/", tags=["Sistema"])
def health_check():
    return {"status": "online", "environment": settings.ENVIRONMENT, "version": settings.VERSION}