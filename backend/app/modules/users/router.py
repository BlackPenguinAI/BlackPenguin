from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user
from app.core.security import verify_password, get_password_hash, verify_email_token
from .models import User
from .schemas import MyProfileUpdate, MyProfileResponse, PasswordUpdatePayload, SetPasswordPayload
from app.modules.companies.models import Company

router = APIRouter()

@router.get("/me", response_model=MyProfileResponse)
def get_my_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile_data = {
        "email": current_user.email,
        "first name": current_user.first_name,
        "last_name": current_user.last_name,
    }
    if current_user.company_id:
        company = db.query(Company).options(joinedload(Company.plan)).filter(Company.id == current_user.company_id).first()
        if company:
            profile_data.update({
                "company_name": company.name,
                "license_start": company.license_start,
                "license_end": company.license_end,
                "plan_name": company.plan.name if company.plan else None
            })
    return profile_data

@router.put("/me")
def update_my_profile(payload: MyProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.first_name = payload.first_name
    current_user.last_name = payload.last_name
    
    if current_user.company_id and payload.company_name:
        company = db.query(Company).filter(Company.id == current_user.company_id).first()
        if company: company.name = payload.company_name

    db.commit()
    return {"message": "Perfil actualizado."}

@router.put("/change-password")
def change_password(payload: PasswordUpdatePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta.")
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Contraseña actualizada."}

@router.post("/set-password")
def set_password(payload: SetPasswordPayload, db: Session = Depends(get_db)):
    token_data = verify_email_token(payload.token)
    if not token_data: raise HTTPException(status_code=400, detail="Enlace inválido o expirado.")
    user = db.query(User).filter(User.email == token_data.get("sub")).first()
    if not user: raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    
    expected_sec = user.hashed_password[-10:] if user.hashed_password else ""
    if token_data.get("sec") != expected_sec:
        raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
        
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Contraseña establecida con éxito."}