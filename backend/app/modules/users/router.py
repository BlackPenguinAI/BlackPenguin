from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user, RoleChecker
from app.core.security import verify_password, get_password_hash, verify_email_token
from .models import User, UserRole
from .schemas import MyProfileUpdate, MyProfileResponse, PasswordUpdatePayload, SetPasswordPayload, UserAdminListResponse
from app.modules.companies.models import Company

router = APIRouter()

@router.get("/me", response_model=MyProfileResponse)
def get_my_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile_data = {
        "email": current_user.email,
        "first_name": current_user.first_name, # 🚀 CORREGIDO (antes decía "first name")
        "last_name": current_user.last_name,
        "phone": current_user.phone,           # 🚀 AÑADIDO
        "country": current_user.country,       # 🚀 AÑADIDO
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
    # 🚀 ACTUALIZAMOS TODOS LOS CAMPOS
    current_user.first_name = payload.first_name
    current_user.last_name = payload.last_name
    current_user.phone = payload.phone
    current_user.country = payload.country
    
    if current_user.company_id and payload.company_name:
        company = db.query(Company).filter(Company.id == current_user.company_id).first()
        if company: 
            company.name = payload.company_name

    db.commit()
    return {"message": "Profile updated successfully."}

# ... (Las rutas de change-password y set-password se mantienen idénticas)
@router.put("/change-password")
def change_password(payload: PasswordUpdatePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password incorrect.")
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully."}

@router.post("/set-password")
def set_password(payload: SetPasswordPayload, db: Session = Depends(get_db)):
    token_data = verify_email_token(payload.token)
    if not token_data: raise HTTPException(status_code=400, detail="Invalid or expired link.")
    user = db.query(User).filter(User.email == token_data.get("sub")).first()
    if not user: raise HTTPException(status_code=404, detail="User not found.")
    
    expected_sec = user.hashed_password[-10:] if user.hashed_password else ""
    if token_data.get("sec") != expected_sec:
        raise HTTPException(status_code=400, detail="This link was already used.")
        
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Password set successfully."}

# ==========================================
# LISTAR TODOS LOS USUARIOS (SUPERADMIN)
# ==========================================
@router.get("/all", response_model=List[UserAdminListResponse])
def get_all_users_for_admin(
    company_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    first_name: Optional[str] = Query(None),
    last_name: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Retorna el listado global de usuarios filtrable por compañía, rol y datos personales."""
    query = db.query(User).options(joinedload(User.company))

    if company_id:
        query = query.filter(User.company_id == company_id)
    if role:
        query = query.filter(User.role == role)
    if first_name:
        query = query.filter(User.first_name.ilike(f"%{first_name}%"))
    if last_name:
        query = query.filter(User.last_name.ilike(f"%{last_name}%"))
    if email:
        query = query.filter(User.email.ilike(f"%{email}%"))

    return query.order_by(User.email.asc()).all()