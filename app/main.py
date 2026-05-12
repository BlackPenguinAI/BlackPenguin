from fastapi import FastAPI
from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware
from app.api.v1 import superadmin

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

# Registramos el Middleware de aislamiento
app.add_middleware(MultiTenantMiddleware)

# Registramos las rutas de la API
app.include_router(superadmin.router, prefix=f"{settings.API_V1_STR}/superadmin", tags=["MAU Management"])

@app.get("/", tags=["Health"])
async def root():
    return {"message": "Black Penguin Core API is online", "status": "active"}