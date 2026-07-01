from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from jose import jwt
from app.core.config import settings

class MultiTenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Rutas excluidas del aislamiento perimetral (Rutas públicas)
        path = request.url.path
        if path in ["/", "/docs", "/openapi.json", f"{settings.API_V1_STR}/auth/login", f"{settings.API_V1_STR}/auth/setup-master"]:
            return await call_next(request)

        # 2. Capturar cabecera Authorization
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "No autorizado. Token Bearer ausente."})

        token = auth_header.split(" ")[1]
        
        try:
            # 3. Descifrar Claims del Token
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            request.state.user_email = payload.get("sub")
            request.state.role = payload.get("role")
            request.state.company_id = payload.get("company_id")

            # 4. Control de Aislamiento: Usuarios operativos DEBEN tener un company_id
            if request.state.role != "superadmin" and not request.state.company_id:
                return JSONResponse(status_code=403, content={"detail": "Falta contexto perimetral (company_id)."})

        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "El token ha expirado."})
        except jwt.JWTError:
            return JSONResponse(status_code=401, content={"detail": "Token inválido estructuralmente."})

        return await call_next(request)