from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.models.pg_models import User, get_db, Base, engine, UserRole
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings
import uuid

router = APIRouter()

@router.post("/setup-master", status_code=201)
def setup_initial_database(db: Session = Depends(get_db)):
    """Ruta utilitaria local para autogenerar las tablas e insertar un Superadmin global de pruebas"""
    Base.metadata.create_all(bind=engine)
    
    # Verificar si ya existe el superadmin
    existing = db.query(User).filter(User.email == settings.FIRST_SUPERADMIN_EMAIL).first()
    if existing:
        return {"message": "La base de datos ya se encuentra inicializada con el usuario administrador."}
        
    master_user = User(
        id=str(uuid.uuid4()),
        email=settings.FIRST_SUPERADMIN_EMAIL,
        hashed_password=get_password_hash(settings.FIRST_SUPERADMIN_PASSWORD),
        role=UserRole.SUPERADMIN,
        is_active=True
    )
    
    db.add(master_user)
    db.commit()
    
    return {
        "status": "success",
        "message": "Estructura Core desplegada correctamente. Administrador inicial registrado."
    }

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Inicia sesión y obtiene el Token JWT. En Swagger, usa el botón verde 'Authorize' de arriba."""
    # OAuth2PasswordRequestForm nombra el campo obligatoriamente como 'username', pero nosotros le pasamos el email
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="El usuario se encuentra inactivo.")
        
    # Construimos la carga útil del Token (Payload)
    token_payload = {
        "sub": str(user.id),
        "role": user.role,
        "company_id": str(user.company_id) if user.company_id else None
    }
    
    access_token = create_access_token(data=token_payload)
    
    return {"access_token": access_token, "token_type": "bearer"}