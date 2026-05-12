from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from .security import decode_jwt_token

class MultiTenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Excluir rutas públicas (Documentación y Login)
        if request.url.path in ["/", "/docs", "/openapi.json", "/api/v1/auth/login"]:
            return await call_next(request)

        # 2. Validar presencia de Bearer Token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="No autorizado")

        token = auth_header.split(" ")[1]
        
        try:
            payload = decode_jwt_token(token)
            # Inyectamos el tenant en el estado de la petición
            request.state.company_id = payload.get("company_id")
            request.state.role = payload.get("role")
            
            # Bloqueo: Si no es Superadmin, DEBE tener un company_id
            if request.state.role != "superadmin" and not request.state.company_id:
                 raise HTTPException(status_code=403, detail="Contexto de empresa no encontrado")

        except Exception:
            raise HTTPException(status_code=401, detail="Token inválido o expirado")

        return await call_next(request)