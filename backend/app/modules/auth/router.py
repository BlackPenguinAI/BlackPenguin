from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.core.security import verify_password, create_access_token
from app.modules.users.models import User
from .schemas import TokenResponse

router = APIRouter()

@router.post("/login", response_model=TokenResponse, summary="Iniciar Sesión")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Correo o contraseña incorrectos.")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo. Contacte a soporte.")

    # Generar Token
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role, "company_id": user.company_id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "name": user.first_name or "Usuario"
    }