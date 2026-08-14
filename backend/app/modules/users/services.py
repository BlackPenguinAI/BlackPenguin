import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import create_email_token, get_password_hash
from app.modules.companies.models import Company
from app.modules.users.models import User, UserRole


INVITABLE_TENANT_ROLES = {
    UserRole.ASSISTANT,
    UserRole.MKT,
    UserRole.SALES,
}


def enforce_role_limit(db: Session, company: Company, role: UserRole) -> None:
    if not company.plan:
        raise HTTPException(status_code=409, detail="The Company does not have an assigned plan.")
    limit_by_role = {
        UserRole.ASSISTANT: company.plan.max_assistants,
        UserRole.MKT: company.plan.max_mkt_users,
        UserRole.SALES: company.plan.max_sales_users,
    }
    if role not in limit_by_role:
        raise HTTPException(
            status_code=403,
            detail="The Company administrator is managed from the superadmin Company panel.",
        )
    limit = limit_by_role[role]
    used = db.query(User).filter(
        User.company_id == company.id,
        User.role == role,
        User.is_active.is_(True),
    ).count()
    if used >= limit:
        raise HTTPException(
            status_code=409,
            detail=f"The plan allows {limit} active {role.value} users.",
        )


def invite_tenant_user(
    db: Session,
    *,
    company_id: str,
    email: str,
    first_name: str,
    last_name: str,
    role: UserRole,
    commit: bool = True,
    send_activation_email: bool = True,
) -> User:
    """Create one non-administrator tenant account for every invitation surface."""
    if role not in INVITABLE_TENANT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only Assistant, Marketing and Sales users can be invited.",
        )
    normalized_email = email.strip().casefold()
    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(status_code=409, detail="The email is already registered.")
    company = db.query(Company).options(joinedload(Company.plan)).filter(
        Company.id == company_id,
        Company.is_active.is_(True),
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="Active Company not found.")
    enforce_role_limit(db, company, role)
    user = User(
        company_id=company_id,
        email=normalized_email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        role=role,
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        is_active=True,
    )
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
        if send_activation_email:
            try:
                send_user_activation(user)
            except Exception:
                # The account remains valid; activation can be resent independently.
                pass
    else:
        db.flush()
    return user

def send_user_activation(user: User):
    """Genera token de 1 uso y dispara Firebase."""
    from app.integrations.firebase_client import send_activation_email

    token = create_email_token(email=user.email, user_hash=user.hashed_password)
    # Aquí irá la URL de tu frontend
    activation_link = f"https://blackpenguin.ai/set-password?token={token}"
    send_activation_email(user.email, activation_link)
