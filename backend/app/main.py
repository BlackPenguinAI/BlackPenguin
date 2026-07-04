from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware

# Importamos la conexión de Mongo
from app.db.mongo import connect_to_mongo, close_mongo_connection

# Importamos los Módulos de Dominio (Routers)
from app.modules.auth.router import router as auth_router
from app.modules.tenants.router import router as tenants_router
from app.modules.properties.router import router as properties_router
from app.modules.sales.router import router as sales_router
from app.modules.ai.router import router as ai_router
from app.modules.integrations.webhooks import router as webhooks_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()

app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    description="SaaS Core Backend modular con arquitectura DDD.",
    lifespan=lifespan 
)

# 🚀 CONFIGURACIÓN DE CORS (Actualizada para Producción Segura)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",         # Para tu desarrollo local
        "https://blackpenguin.ai",       # Dominio principal
        "https://www.blackpenguin.ai"    # Dominio con www
    ], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# =================================================================
# REGISTRO DE RUTAS POR DOMINIO
# =================================================================
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["1. Seguridad"])
app.include_router(tenants_router, prefix=f"{settings.API_V1_STR}/superadmin", tags=["2. SaaS / Tenants"])
app.include_router(properties_router, prefix=f"{settings.API_V1_STR}/projects", tags=["3. Proyectos"])
app.include_router(sales_router, prefix=f"{settings.API_V1_STR}/leads", tags=["4. Ventas (Leads)"])
app.include_router(ai_router, prefix=f"{settings.API_V1_STR}/conversations", tags=["5. IA & Chat"])
app.include_router(webhooks_router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["6. Integraciones"])