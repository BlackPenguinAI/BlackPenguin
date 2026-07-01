from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware

# Importamos las rutas
from app.api.v1 import auth, superadmin, projects, webhooks, leads, conversations
# Importamos el gestor de MongoDB
from app.models.mongo_models import connect_to_mongo, close_mongo_connection

# =================================================================
# GESTOR DEL CICLO DE VIDA DEL SERVIDOR (STARTUP / SHUTDOWN)
# =================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Se ejecuta al iniciar Uvicorn / Docker
    await connect_to_mongo()
    yield
    # Se ejecuta al detener el servidor (Ctrl+C o detención de contenedor)
    await close_mongo_connection()

app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    description="API Core para la gestión Multi-tenant, ingesta omnicanal de leads y enrutamiento de IA en ventas inmobiliarias.",
    lifespan=lifespan # Conectamos el ciclo de vida de bases de datos
)

# Registrar el Middleware de Aislamiento Perimetral Multi-tenant
app.add_middleware(MultiTenantMiddleware)

# =================================================================
# RUTAS DE LA API (V1)
# =================================================================
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["1. Seguridad y Autenticación"])
app.include_router(superadmin.router, prefix=f"{settings.API_V1_STR}/superadmin", tags=["2. Gestión de Plataforma (SaaS Admin)"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["3. Proyectos Inmobiliarios"])
app.include_router(webhooks.router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["4. Ingesta de Leads y Webhooks"])
app.include_router(leads.router, prefix=f"{settings.API_V1_STR}/leads", tags=["5. Gestión de Leads (Ventas)"])

# REGISTRO DEL MOTOR DE IA (SEMANA 6 - CONVERSATIONS)
app.include_router(conversations.router, prefix=f"{settings.API_V1_STR}/conversations", tags=["6. Memoria Cognitiva IA"])

@app.get("/", tags=["Sistema"])
def health_check():
    return {
        "status": "online", 
        "environment": settings.ENVIRONMENT, 
        "version": settings.VERSION,
        "message": "Black Penguin Core Core Engine running smoothly."
    }