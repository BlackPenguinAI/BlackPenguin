from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user, RoleChecker
from app.core.security import verify_password, get_password_hash, verify_email_token
from .models import TENANT_MANAGER_ROLES, User, UserRole
from .project_access import project_ids_for_user, sync_user_project_access
from . import services
from .schemas import (
    CompanyProjectOption, MyProfileUpdate, MyProfileResponse, PasswordUpdatePayload, SetPasswordPayload,
    TenantUserCreate, TenantUserResponse, TenantUserUpdate, UserAdminListResponse,
)
from app.modules.companies.models import Company
from app.modules.projects.models import Project

router = APIRouter()


def _tenant_user_response(db: Session, user: User) -> dict:
    project_ids = project_ids_for_user(db, user)
    return {
        "id": user.id, "email": user.email, "first_name": user.first_name,
        "last_name": user.last_name, "phone": user.phone, "country": user.country,
        "timezone": user.timezone or "UTC", "role": user.role, "is_active": user.is_active,
        "project_access_scope": "all" if user.role == UserRole.ADMIN else (user.project_access_scope or "all"),
        "project_ids": project_ids,
        "project_assignment_required": bool(
            user.role in (UserRole.MKT, UserRole.SALES)
            and (user.project_access_scope or "all") == "selected" and not project_ids
        ),
    }


@router.get("/me", response_model=MyProfileResponse)
def get_my_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile_data = {
        "email": current_user.email,
        "role": current_user.role,
        "first_name": current_user.first_name, # 🚀 CORREGIDO (antes decía "first name")
        "last_name": current_user.last_name,
        "phone": current_user.phone,           # 🚀 AÑADIDO
        "country": current_user.country,       # 🚀 AÑADIDO
        "timezone": current_user.timezone or "UTC",
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
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    # 🚀 ACTUALIZAMOS TODOS LOS CAMPOS
    current_user.first_name = payload.first_name
    current_user.last_name = payload.last_name
    current_user.phone = payload.phone
    current_user.country = payload.country
    if payload.timezone is not None:
        current_user.timezone = payload.timezone
    
    if current_user.company_id and payload.company_name and current_user.role in TENANT_MANAGER_ROLES:
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
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    users = db.query(User).filter(User.company_id == current_user.company_id).order_by(User.email.asc()).all()
    return [_tenant_user_response(db, user) for user in users]


@router.post("/company", response_model=TenantUserResponse, status_code=status.HTTP_201_CREATED)
def invite_company_user(
    payload: TenantUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    try:
        role = UserRole(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.") from exc
    user = services.create_tenant_user(
        db,
        company_id=current_user.company_id,
        email=str(payload.email),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=role,
        password=payload.password,
        is_active=payload.is_active,
        timezone=payload.timezone,
        project_access_scope=payload.project_access_scope,
        project_ids=payload.project_ids,
    )
    return _tenant_user_response(db, user)


@router.get("/company/limits")
def get_company_user_limits(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    company = db.query(Company).options(joinedload(Company.plan)).filter(
        Company.id == current_user.company_id,
    ).first()
    if not company or not company.plan:
        raise HTTPException(status_code=409, detail="The Company does not have an assigned plan.")
    result = {}
    for role, limit in (
        (UserRole.ASSISTANT, company.plan.max_assistants),
        (UserRole.MKT, company.plan.max_mkt_users),
        (UserRole.SALES, company.plan.max_sales_users),
    ):
        result[role.value] = {
            "used": db.query(User).filter(
                User.company_id == current_user.company_id,
                User.role == role,
                User.is_active.is_(True),
            ).count(),
            "limit": limit,
        }
    return result


@router.get("/company/projects", response_model=List[CompanyProjectOption])
def list_company_project_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    query = db.query(Project).filter(
        Project.company_id == current_user.company_id,
        Project.is_active.is_(True),
    )
    if current_user.role == UserRole.ASSISTANT and (current_user.project_access_scope or "all") == "selected":
        allowed = project_ids_for_user(db, current_user)
        query = query.filter(Project.id.in_(allowed)) if allowed else query.filter(Project.id == "")
    return query.order_by(Project.name).all()


@router.patch("/company/{user_id}", response_model=TenantUserResponse)
def update_company_user(
    user_id: str,
    payload: TenantUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="The Company administrator can only be managed from the superadmin Company panel.",
        )
    try:
        next_role = UserRole(payload.role) if payload.role is not None else user.role
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.") from exc
    if next_role not in services.INVITABLE_TENANT_ROLES:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.")
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    if next_active and (not user.is_active or next_role != user.role):
        company = db.query(Company).options(joinedload(Company.plan)).filter(
            Company.id == current_user.company_id,
        ).first()
        services.enforce_role_limit(db, company, next_role)
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    values = payload.model_dump(
        exclude_unset=True,
        exclude={"password", "project_access_scope", "project_ids", "role"},
    )
    for key, value in values.items():
        setattr(user, key, value)
    user.role = next_role
    if payload.password:
        user.hashed_password = get_password_hash(payload.password)
    scope = payload.project_access_scope or user.project_access_scope or "all"
    selected_ids = payload.project_ids if payload.project_ids is not None else project_ids_for_user(db, user)
    sync_user_project_access(db, user=user, scope=scope, project_ids=selected_ids)
    db.commit()
    db.refresh(user)
    return _tenant_user_response(db, user)


@router.post("/company/{user_id}/resend-activation")
def resend_company_user_activation(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="The Company administrator can only be managed from the superadmin Company panel.",
        )
    services.send_user_activation(user)
    return {"detail": "Activation link sent."}
