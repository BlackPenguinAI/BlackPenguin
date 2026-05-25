from fastapi import FastAPI
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware
from app.api.v1 import auth, superadmin

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

# Registrar el Middleware de Aislamiento Perimetral (Semana 4)
app.add_middleware(MultiTenantMiddleware)

# Rutas de la API v1
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Autenticación"])
app.include_router(superadmin.router, prefix=f"{settings.API_V1_STR}/superadmin", tags=["Aprovisionamiento MAU"])

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "online", "environment": "local_dev", "version": settings.VERSION}