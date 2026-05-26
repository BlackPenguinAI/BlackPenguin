from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.pg_models import User, Company, get_db, Base, engine, UserRole
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings # Inyectamos la configuración limpia
import uuid

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/setup-master", status_code=201)
def setup_initial_database(db: Session = Depends(get_db)):
    """Ruta utilitaria local para autogenerar las tablas e insertar un Superadmin global de pruebas"""
    # Genera la estructura física en PostgreSQL (blackpenguin_db)
    Base.metadata.create_all(bind=engine)
    
    # Verificar si ya existe el superadmin leyendo desde las variables secretas
    existing = db.query(User).filter(User.email == settings.FIRST_SUPERADMIN_EMAIL).first()
    if existing:
        return {"message": "La base de datos ya se encuentra inicializada con el usuario administrador."}
        
    # Creamos el registro del dueño del SaaS de manera dinámica y protegida
    master_user = User(
        id=str(uuid.uuid4()), # Usamos un UUID real en lugar de un texto fijo para producción
        email=settings.FIRST_SUPERADMIN_EMAIL,
        hashed_password=get_password_hash(settings.FIRST_SUPERADMIN_PASSWORD),
        role=UserRole.SUPERADMIN,
        is_active=True
    )
    
    db.add(master_user)
    db.commit()
    
    return {
        "status": "success",
        "message": f"Estructura Core desplegada correctamente. Administrador inicial registrado bajo el alias configurado en el entorno seguro."
    }