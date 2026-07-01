from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import uuid

from app.db.postgres import get_db, Base, engine
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings

# Importamos los modelos para asegurar que SQLAlchemy los construya en setup-master
from app.modules.tenants.models import Company
from app.modules.auth.models import User, UserRole

router = APIRouter()

@router.post("/setup-master", status_code=201)
def setup_initial_database(db: Session = Depends(get_db)):
    """Inicializa la DB y crea el superadmin maestro."""
    Base.metadata.create_all(bind=engine)
    
    existing = db.query(User).filter(User.email == settings.FIRST_SUPERADMIN_EMAIL).first()
    if existing:
        return {"message": "La base de datos ya se encuentra inicializada."}
        
    master_user = User(
        email=settings.FIRST_SUPERADMIN_EMAIL,
        hashed_password=get_password_hash(settings.FIRST_SUPERADMIN_PASSWORD),
        role=UserRole.SUPERADMIN
    )
    db.add(master_user)
    db.commit()
    
    return {"status": "success", "message": "Superadmin maestro registrado."}

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo.")
        
    token_payload = {
        "sub": str(user.id),
        "role": user.role,
        "company_id": str(user.company_id) if user.company_id else None
    }
    access_token = create_access_token(data=token_payload)
    return {"access_token": access_token, "token_type": "bearer"}