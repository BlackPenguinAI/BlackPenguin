from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from jose import jwt
from app.core.config import settings

class MultiTenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 🚀 NUEVO: Permitir acceso público a las rutas legales SOLO para lectura (GET)
        is_public_legal_route = request.method == "GET" and path.startswith(f"{settings.API_V1_STR}/system/legal/")

        # Rutas exentas de token (Login, Configuración inicial, Docs y Legales Públicos)
        if path in ["/", "/docs", "/openapi.json", f"{settings.API_V1_STR}/auth/login", f"{settings.API_V1_STR}/auth/setup-master"] or is_public_legal_route:
            return await call_next(request)

        # Validación del token para todo el resto de la aplicación
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "No autorizado. Token Bearer ausente."})

        token = auth_header.split(" ")[1]
        
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            request.state.user_email = payload.get("sub")
            request.state.role = payload.get("role")
            request.state.company_id = payload.get("company_id")

            if request.state.role != "superadmin" and not request.state.company_id:
                return JSONResponse(status_code=403, content={"detail": "Falta contexto perimetral (company_id)."})

        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "El token ha expirado."})
        except jwt.JWTError:
            return JSONResponse(status_code=401, content={"detail": "Token inválido."})

        return await call_next(request)