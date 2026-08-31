import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_password_hash
from app.modules.companies.models import Company
from app.modules.users.models import User, UserAuthStatus, UserInvitation, UserRole
from app.modules.users.project_access import sync_user_project_access


INVITABLE_TENANT_ROLES = {UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES}
SEAT_HOLDING_AUTH_STATUSES = {
    UserAuthStatus.INVITED, UserAuthStatus.ACTIVE,
    UserAuthStatus.PROVISIONING_FAILED, UserAuthStatus.MIGRATION_REQUIRED,
}


def enforce_role_limit(db: Session, company: Company, role: UserRole, *, exclude_user_id: str | None = None) -> None:
    if not company.plan:
        raise HTTPException(status_code=409, detail="The Company does not have an assigned plan.")
    limit_by_role = {
        UserRole.ASSISTANT: company.plan.max_assistants,
        UserRole.MKT: company.plan.max_mkt_users,
        UserRole.SALES: company.plan.max_sales_users,
    }
    if role not in limit_by_role:
        raise HTTPException(status_code=403, detail="The Company administrator is managed from the superadmin Company panel.")
    query = db.query(User).filter(
        User.company_id == company.id, User.role == role,
        User.is_active.is_(True),
        User.auth_status.in_(SEAT_HOLDING_AUTH_STATUSES),
    )
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    used = query.count()
    limit = limit_by_role[role]
    if used >= limit:
        raise HTTPException(status_code=409, detail=f"The plan allows {limit} {role.value} users, including pending invitations.")


def _validated_company(db: Session, company_id: str, *, require_active: bool = True) -> Company:
    query = db.query(Company).options(joinedload(Company.plan)).filter(Company.id == company_id)
    if require_active:
        query = query.filter(Company.is_active.is_(True))
    company = query.first()
    if not company:
        raise HTTPException(status_code=404, detail="Active Company not found.")
    return company


def create_tenant_user(
    db: Session, *, company_id: str, email: str, first_name: str, last_name: str,
    role: UserRole, password: str, is_active: bool, timezone: str = "UTC",
    project_access_scope: str = "all", project_ids: list[str] | None = None,
    commit: bool = True, send_activation_email: bool = False,
) -> User:
    """Legacy-compatible local creation used only by migration and tests."""
    if role not in INVITABLE_TENANT_ROLES:
        raise HTTPException(status_code=403, detail="Only Assistant, Marketing and Sales users can be invited.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    normalized_email = email.strip().casefold()
    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(status_code=409, detail="The email is already registered.")
    company = _validated_company(db, company_id)
    if is_active:
        enforce_role_limit(db, company, role)
    user = User(
        company_id=company_id, email=normalized_email, first_name=first_name.strip(),
        last_name=last_name.strip(), role=role, hashed_password=get_password_hash(password),
        is_active=is_active, timezone=timezone, project_access_scope=project_access_scope,
        auth_status=UserAuthStatus.ACTIVE if is_active else UserAuthStatus.SUSPENDED,
        activated_at=datetime.utcnow() if is_active else None,
    )
    db.add(user); db.flush()
    sync_user_project_access(db, user=user, scope=project_access_scope, project_ids=project_ids or [])
    if commit:
        db.commit(); db.refresh(user)
    if send_activation_email:
        provision_invitation(db, user=user)
    return user


def invite_tenant_user(
    db: Session, *, company_id: str, email: str, first_name: str, last_name: str,
    role: UserRole, timezone: str = "UTC", project_access_scope: str = "all",
    project_ids: list[str] | None = None, invited_by_user_id: str | None = None,
    commit: bool = True, send_activation_email: bool = True,
) -> User:
    if role not in INVITABLE_TENANT_ROLES:
        raise HTTPException(status_code=403, detail="Only Assistant, Marketing and Sales users can be invited.")
    user = _create_pending_user(
        db, company_id=company_id, email=email, first_name=first_name, last_name=last_name,
        role=role, timezone=timezone, project_access_scope=project_access_scope,
        project_ids=project_ids, invited_by_user_id=invited_by_user_id,
    )
    if commit:
        db.commit(); db.refresh(user)
    if send_activation_email:
        provision_invitation(db, user=user, invited_by_user_id=invited_by_user_id)
    return user


def invite_company_administrator(
    db: Session, *, company_id: str, email: str, first_name: str, last_name: str,
    is_active: bool = True, invited_by_user_id: str | None = None,
) -> User:
    user = _create_pending_user(
        db, company_id=company_id, email=email, first_name=first_name, last_name=last_name,
        role=UserRole.ADMIN, timezone="UTC", project_access_scope="all", project_ids=[],
        invited_by_user_id=invited_by_user_id, enforce_limit=False,
        require_active_company=False,
    )
    if not is_active:
        user.is_active = False
        user.auth_status = UserAuthStatus.SUSPENDED
    db.commit(); db.refresh(user)
    if is_active:
        provision_invitation(db, user=user, invited_by_user_id=invited_by_user_id)
    return user


def _create_pending_user(
    db: Session, *, company_id: str, email: str, first_name: str, last_name: str,
    role: UserRole, timezone: str, project_access_scope: str, project_ids: list[str] | None,
    invited_by_user_id: str | None, enforce_limit: bool = True,
    require_active_company: bool = True,
) -> User:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    normalized_email = email.strip().casefold()
    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(status_code=409, detail="The email is already registered.")
    company = _validated_company(db, company_id, require_active=require_active_company)
    if enforce_limit:
        enforce_role_limit(db, company, role)
    user = User(
        company_id=company_id, email=normalized_email, first_name=first_name.strip(),
        last_name=last_name.strip(), role=role,
        hashed_password=get_password_hash(secrets.token_urlsafe(48)),
        is_active=True, timezone=timezone, project_access_scope=project_access_scope,
        auth_status=UserAuthStatus.INVITED,
    )
    db.add(user); db.flush()
    sync_user_project_access(db, user=user, scope=project_access_scope, project_ids=project_ids or [])
    return user


def provision_invitation(db: Session, *, user: User, invited_by_user_id: str | None = None) -> UserInvitation:
    from app.integrations.firebase_client import create_identity, send_password_action_email

    invitation = UserInvitation(
        user_id=user.id, invited_by_user_id=invited_by_user_id, status="pending",
        expires_at=datetime.utcnow() + timedelta(days=7), send_attempts=1,
    )
    db.add(invitation); db.commit(); db.refresh(user); db.refresh(invitation)
    try:
        identity = create_identity(
            db, uid=user.id, email=user.email,
            display_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
            password=secrets.token_urlsafe(48),
        )
        user.firebase_uid = identity.uid
        send_password_action_email(db, user.email)
        now = datetime.utcnow()
        user.auth_status = UserAuthStatus.INVITED
        user.invitation_sent_at = now
        invitation.sent_at = now
        invitation.last_error = None
    except HTTPException as exc:
        user.auth_status = UserAuthStatus.PROVISIONING_FAILED
        invitation.status = "delivery_failed"
        invitation.last_error = str(exc.detail)[:500]
    db.commit(); db.refresh(user); db.refresh(invitation)
    return invitation


def resend_user_activation(db: Session, *, user: User, invited_by_user_id: str | None = None) -> UserInvitation:
    if user.auth_status == UserAuthStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="This user has already activated the account.")
    latest = db.query(UserInvitation).filter(UserInvitation.user_id == user.id).order_by(UserInvitation.created_at.desc()).first()
    if latest and latest.sent_at and latest.sent_at > datetime.utcnow() - timedelta(seconds=60):
        raise HTTPException(status_code=429, detail="Wait one minute before resending the invitation.")
    return provision_invitation(db, user=user, invited_by_user_id=invited_by_user_id)


def set_user_enabled(db: Session, *, user: User, enabled: bool) -> None:
    from app.integrations.firebase_client import update_identity
    user.is_active = enabled
    if enabled:
        user.auth_status = UserAuthStatus.ACTIVE if user.activated_at else UserAuthStatus.INVITED
    else:
        user.auth_status = UserAuthStatus.SUSPENDED
    if user.firebase_uid:
        update_identity(db, uid=user.firebase_uid, disabled=not enabled)


def mark_invitation_accepted(db: Session, user: User) -> None:
    from app.integrations.firebase_client import update_identity
    now = datetime.utcnow()
    user.auth_status = UserAuthStatus.ACTIVE
    user.is_active = True
    user.activated_at = user.activated_at or now
    user.last_login_at = now
    invitation = db.query(UserInvitation).filter(
        UserInvitation.user_id == user.id,
        UserInvitation.status.in_(["pending", "delivery_failed"]),
    ).order_by(UserInvitation.created_at.desc()).first()
    if invitation:
        invitation.status = "accepted"
        invitation.accepted_at = now
    if user.firebase_uid:
        update_identity(db, uid=user.firebase_uid, email_verified=True, disabled=False)
    db.commit()
