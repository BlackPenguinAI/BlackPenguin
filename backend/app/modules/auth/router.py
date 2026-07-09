from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uuid

from app.db.postgres import get_db, Base, engine
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings

# Importamos los modelos
from app.modules.tenants.models import Company
from app.modules.auth.models import User, UserRole

from app.modules.auth.schemas import UserProfileUpdate, UserProfileResponse
from app.modules.auth.deps import get_current_user

router = APIRouter()

# --- SCHEMAS DE PYDANTIC (Validan los datos que envía Angular) ---
class UserCreate(BaseModel):
    full_name: str  
    email: str
    password: str
    role: str = "admin"
    is_active: bool = True

# --- ENDPOINTS ---

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

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Este correo ya está registrado.")
        
    new_user = User(
        full_name=user_data.full_name, # 🚀 Guardamos el nombre
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        is_active=user_data.is_active
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Cuenta creada exitosamente", "user_id": new_user.id}

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Este correo no está registrado.")
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo.")
        
    access_token = create_access_token(data={"sub": user.email})
    
    # 🚀 ENTRGA CRÍTICA: Añadimos role y name en la respuesta raíz para Angular
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role.value if hasattr(user.role, 'value') else str(user.role),
        "name": user.full_name
    }

@router.get("/me", response_model=UserProfileResponse, summary="Obtener mi perfil")
def get_my_profile(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/me", response_model=UserProfileResponse, summary="Actualizar mi perfil")
def update_my_profile(
    payload: UserProfileUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)
        
    db.commit()
    db.refresh(current_user)
    return current_user