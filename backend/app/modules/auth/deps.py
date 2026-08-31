from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from typing import List, Any

from app.core.config import settings
from app.db.postgres import get_db

# 🚀 IMPORTAMOS USER DESDE SU NUEVO MÓDULO
from app.modules.users.models import User, UserAuthStatus

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales de acceso.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_email: str = payload.get("sub")
        if token_email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == token_email).first()
    if user is None or not user.is_active or user.auth_status == UserAuthStatus.SUSPENDED:
        raise credentials_exception
    return user

class RoleChecker:
    def __init__(self, allowed_roles: List[Any]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)):
        user_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
        allowed = [r.value if hasattr(r, 'value') else str(r) for r in self.allowed_roles]
        
        if user_role not in allowed:
            raise HTTPException(status_code=403, detail="No tienes permisos para realizar esta acción.")
        return current_user
