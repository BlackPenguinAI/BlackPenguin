from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # 🚀 ¡ESTA ES LA LÍNEA QUE FALTABA!
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

# 🚀 CONFIGURACIÓN DE CORS (Debe ser el primer middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"], # Permite que Angular se conecte
    allow_credentials=True,
    allow_methods=["*"], # Esto es clave: Permite OPTIONS, POST, GET, etc.
    allow_headers=["*"], # Permite que Angular envíe cualquier cabecera
)

# =================================================================
# REGISTRO DE RUTAS POR DOMINIO
# =================================================================
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["1. Seguridad"])
app.include_router(tenants_router, prefix=f"{settings.API_V1_STR}/superadmin", tags=["2. SaaS / Tenants"])
app.include_router(properties_router, prefix=f"{settings.API_V1_STR}/projects", tags=["3. Proyectos"])
app.include_router(sales_router, prefix=f"{settings.API_V1_STR}/leads", tags=["4. Ventas (Leads)"])
app.include_router(ai_router, prefix=f"{settings.API_V1_STR}/conversations", tags=["5. IA / OpenRouter"])
app.include_router(webhooks_router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["6. Integraciones (Meta)"])

@app.get("/", tags=["Sistema"])
def health_check():
    return {"status": "online", "environment": settings.ENVIRONMENT, "version": settings.VERSION}