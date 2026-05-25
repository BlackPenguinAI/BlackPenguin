from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.pg_models import User, Company, get_db, Base, engine, UserRole
from app.core.security import verify_password, get_password_hash, create_access_token
from datetime import datetime, timedelta

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/setup-master", status_code=201)
def setup_initial_database(db: Session = Depends(get_db)):
    """Ruta utilitaria local para autogenerar las tablas e insertar un Superadmin global de pruebas"""
    Base.metadata.create_all(bind=engine)
    
    # Verificar si ya existe el superadmin
    existing = db.query(User).filter(User.email == "superadmin@blackpenguin.ai").first()
    if existing:
        return {"message": "La base de datos local ya se encuentra inicializada."}
        
    master_user = User(
        id="master-uuid-112233",
        email="superadmin@blackpenguin.ai",
        hashed_password=get_password_hash("bp_master_2026"),
        role=UserRole.SUPERADMIN,
        is_active=True
    )
    db.add(master_user)
    db.commit()
    return {"message": "Tablas v2.0 creadas con éxito. Usuario superadmin@blackpenguin.ai (pass: bp_master_2026) creado."}

@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    
    # Generar token inyectando el rol y contexto multi-tenant
    token = create_access_token(subject=user.email, role=user.role.value, company_id=user.company_id)
    return {"access_token": token, "token_type": "bearer"}