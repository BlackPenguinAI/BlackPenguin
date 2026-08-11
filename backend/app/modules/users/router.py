from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import secrets

from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user, RoleChecker
from app.core.security import verify_password, get_password_hash, verify_email_token
from .models import User, UserRole
from .schemas import (
    MyProfileUpdate, MyProfileResponse, PasswordUpdatePayload, SetPasswordPayload,
    TenantUserCreate, TenantUserResponse, TenantUserUpdate, UserAdminListResponse,
)
from app.modules.companies.models import Company

router = APIRouter()


def _enforce_role_limit(db: Session, company: Company, role: UserRole) -> None:
    if not company.plan:
        raise HTTPException(status_code=409, detail="The Company does not have an assigned plan.")
    limit_by_role = {
        UserRole.ADMIN: company.plan.max_admins,
        UserRole.MKT: company.plan.max_mkt_users,
        UserRole.SALES: company.plan.max_sales_users,
    }
    limit = limit_by_role[role]
    used = db.query(User).filter(
        User.company_id == company.id,
        User.role == role,
        User.is_active.is_(True),
    ).count()
    if used >= limit:
        raise HTTPException(status_code=409, detail=f"The plan allows {limit} active {role.value} users.")

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


@router.get("/company", response_model=List[TenantUserResponse])
def list_company_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    return db.query(User).filter(User.company_id == current_user.company_id).order_by(User.email.asc()).all()


@router.post("/company", response_model=TenantUserResponse, status_code=status.HTTP_201_CREATED)
def invite_company_user(
    payload: TenantUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    try:
        role = UserRole(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Role must be admin, mkt or sales.") from exc
    if role == UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Company admins cannot create superadmins.")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="The email is already registered.")
    company = db.query(Company).options(joinedload(Company.plan)).filter(Company.id == current_user.company_id).first()
    _enforce_role_limit(db, company, role)
    user = User(
        company_id=current_user.company_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=role,
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    try:
        from .services import send_user_activation
        send_user_activation(user)
    except Exception:
        # The account remains valid; resend can be retried independently.
        pass
    return user


@router.patch("/company/{user_id}", response_model=TenantUserResponse)
def update_company_user(
    user_id: str,
    payload: TenantUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.is_active is False and user.role == UserRole.ADMIN:
        active_admins = db.query(User).filter(
            User.company_id == current_user.company_id,
            User.role == UserRole.ADMIN,
            User.is_active.is_(True),
        ).count()
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="The last active Company admin cannot be deactivated.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


@router.post("/company/{user_id}/resend-activation")
def resend_company_user_activation(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    from .services import send_user_activation
    send_user_activation(user)
    return {"detail": "Activation link sent."}
