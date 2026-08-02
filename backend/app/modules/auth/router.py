from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.postgres import get_db
from app.core.security import verify_password, create_access_token, get_password_hash
from app.modules.users.models import User
from app.modules.auth.deps import get_current_user 

from .schemas import TokenResponse

router = APIRouter()

# ==========================================
# 1. INICIAR SESIÓN
# ==========================================
@router.post("/login", response_model=TokenResponse, summary="Iniciar Sesión")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Correo o contraseña incorrectos.")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo. Contacte a soporte.")

    access_token = create_access_token(
        data={"sub": user.email, "role": user.role, "company_id": user.company_id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "name": user.first_name or "Usuario"
    }

# ==========================================
# 2. CAMBIAR CONTRASEÑA
# ==========================================
class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str

@router.put("/change-password/", status_code=status.HTTP_200_OK, summary="Cambiar Contraseña")
def change_password(
    payload: ChangePasswordPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Permite a cualquier usuario autenticado cambiar su propia contraseña.
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
        
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    
    return {"detail": "Password updated successfully"}