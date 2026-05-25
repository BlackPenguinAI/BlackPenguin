from fastapi import Request, HTTPException, Depends
from typing import List

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, request: Request):
        user_role = getattr(request.state, "role", None)
        if not user_role or user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Permisos insuficientes. Requiere roles: {self.allowed_roles}"
            )
        return user_role

require_superadmin = RoleChecker(["superadmin"])
require_admin = RoleChecker(["superadmin", "admin"])