import logging
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.security import create_invitation_state, get_password_hash
from app.modules.companies.models import Company
from app.modules.users.models import User, UserAuthStatus, UserInvitation, UserRole
from app.modules.users.project_access import project_ids_for_user, sync_user_project_access


logger = logging.getLogger(__name__)
INVITABLE_TENANT_ROLES = {UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES}
SEAT_HOLDING_AUTH_STATUSES = {
    UserAuthStatus.INVITED, UserAuthStatus.ACTIVE,
    UserAuthStatus.PROVISIONING_FAILED, UserAuthStatus.MIGRATION_REQUIRED,
}


def normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not 8 <= len(normalized) <= 100:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "Idempotency-Key must contain between 8 and 100 characters.",
            },
        )
    return normalized


def latest_user_invitation(db: Session, user_id: str) -> UserInvitation | None:
    return db.query(UserInvitation).filter(
        UserInvitation.user_id == user_id,
    ).order_by(UserInvitation.created_at.desc()).first()


def invitation_delivery_status(invitation: UserInvitation | None) -> str:
    if invitation is None:
        return "not_applicable"
    if invitation.status == "accepted_by_provider":
        return "sent"
    if invitation.status == "delivery_failed":
        return "failed"
    return "pending"


def invitation_error_code(invitation: UserInvitation | None) -> str | None:
    """Return only a stable provider code, never a raw provider response."""
    if not invitation or not invitation.last_error:
        return None
    candidate = invitation.last_error.strip().split(" : ", 1)[0]
    return candidate if candidate.replace("_", "").isalnum() else "FIREBASE_REQUEST_FAILED"


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
    idempotency_key: str | None = None,
) -> User:
    if role not in INVITABLE_TENANT_ROLES:
        raise HTTPException(status_code=403, detail="Only Assistant, Marketing and Sales users can be invited.")
    if send_activation_email:
        from app.integrations.firebase_client import ensure_firebase_ready
        ensure_firebase_ready(db)
    user = _create_pending_user(
        db, company_id=company_id, email=email, first_name=first_name, last_name=last_name,
        role=role, timezone=timezone, project_access_scope=project_access_scope,
        project_ids=project_ids, invited_by_user_id=invited_by_user_id,
    )
    if commit:
        db.commit(); db.refresh(user)
    if send_activation_email:
        provision_invitation(
            db, user=user, invited_by_user_id=invited_by_user_id,
            idempotency_key=idempotency_key,
        )
    return user


def invite_company_administrator(
    db: Session, *, company_id: str, email: str, first_name: str, last_name: str,
    is_active: bool = True, invited_by_user_id: str | None = None,
) -> User:
    from app.integrations.firebase_client import ensure_firebase_ready
    if is_active:
        ensure_firebase_ready(db)
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
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        if role == UserRole.ADMIN or existing.company_id != company_id:
            raise HTTPException(status_code=409, detail="The email is already registered.")
        pending = existing.auth_status in {
            UserAuthStatus.INVITED, UserAuthStatus.PROVISIONING_FAILED,
        }
        detail = {
            "code": "USER_ALREADY_INVITED" if pending else "EMAIL_ALREADY_REGISTERED",
            "message": (
                "This user is already pending activation."
                if pending else "The email is already registered."
            ),
        }
        detail.update({
            "user_id": existing.id,
            "auth_status": existing.auth_status.value,
            "next_action": "resend_activation" if pending else "view_user",
        })
        raise HTTPException(status_code=409, detail=detail)
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


def invitation_for_idempotency_key(
    db: Session, *, idempotency_key: str, company_id: str, email: str,
    first_name: str | None = None, last_name: str | None = None,
    role: UserRole | None = None, timezone: str | None = None,
    project_access_scope: str | None = None, project_ids: list[str] | None = None,
) -> UserInvitation | None:
    invitation = db.query(UserInvitation).join(User, User.id == UserInvitation.user_id).filter(
        UserInvitation.idempotency_key == idempotency_key,
    ).first()
    different_request = bool(invitation) and (
        invitation.user.company_id != company_id
        or invitation.user.email != email.strip().casefold()
        or (first_name is not None and invitation.user.first_name != first_name.strip())
        or (last_name is not None and invitation.user.last_name != last_name.strip())
        or (role is not None and invitation.user.role != role)
        or (timezone is not None and (invitation.user.timezone or "UTC") != timezone)
        or (
            project_access_scope is not None
            and (invitation.user.project_access_scope or "all") != project_access_scope
        )
        or (
            project_ids is not None
            and set(project_ids_for_user(db, invitation.user)) != set(project_ids)
        )
    )
    if invitation and different_request:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "This invitation request key was already used for different data.",
            },
        )
    return invitation


def provision_invitation(
    db: Session, *, user: User, invited_by_user_id: str | None = None,
    idempotency_key: str | None = None,
) -> UserInvitation:
    from app.integrations.firebase_client import ensure_firebase_ready, send_email_sign_in_link
    ensure_firebase_ready(db)

    invitation = db.query(UserInvitation).filter(
        UserInvitation.user_id == user.id,
        UserInvitation.status.in_(["pending", "delivery_failed"]),
    ).order_by(UserInvitation.created_at.desc()).first()
    if not invitation:
        invitation = UserInvitation(
            user_id=user.id, invited_by_user_id=invited_by_user_id, status="pending",
            expires_at=datetime.utcnow() + timedelta(days=7), send_attempts=0,
            idempotency_key=idempotency_key,
        )
        db.add(invitation)
    elif idempotency_key and not invitation.idempotency_key:
        invitation.idempotency_key = idempotency_key
    now = datetime.utcnow()
    invitation.status = "pending"
    invitation.last_attempt_at = now
    invitation.send_attempts = (invitation.send_attempts or 0) + 1
    invitation.expires_at = now + timedelta(days=7)
    db.commit(); db.refresh(user); db.refresh(invitation)
    logger.info(
        "Firebase email-link invitation attempt started company_id=%s user_id=%s invitation_id=%s attempt=%s has_firebase_uid=%s",
        user.company_id, user.id, invitation.id, invitation.send_attempts, bool(user.firebase_uid),
    )
    phase = "send_email_sign_in_link"
    try:
        state = create_invitation_state(invitation.id, user.id, timedelta(days=7))
        send_email_sign_in_link(db, user.email, invitation_state=state)
        now = datetime.utcnow()
        user.auth_status = UserAuthStatus.INVITED
        user.invitation_sent_at = now
        invitation.status = "accepted_by_provider"
        invitation.sent_at = now
        invitation.last_error = None
        invitation.provisioning_secret_ciphertext = None
        logger.info(
            "Firebase activation request accepted company_id=%s user_id=%s invitation_id=%s attempt=%s",
            user.company_id, user.id, invitation.id, invitation.send_attempts,
        )
    except HTTPException as exc:
        user.auth_status = UserAuthStatus.PROVISIONING_FAILED
        invitation.status = "delivery_failed"
        invitation.last_error = str(exc.detail)[:500]
        logger.error(
            "Firebase invitation failed company_id=%s user_id=%s invitation_id=%s attempt=%s phase=%s http_status=%s error_code=%s",
            user.company_id, user.id, invitation.id, invitation.send_attempts,
            phase, exc.status_code, invitation.last_error,
        )
    db.commit(); db.refresh(user); db.refresh(invitation)
    return invitation


def resend_user_activation(db: Session, *, user: User, invited_by_user_id: str | None = None) -> UserInvitation:
    if user.auth_status == UserAuthStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="This user has already activated the account.")
    latest = db.query(UserInvitation).filter(UserInvitation.user_id == user.id).order_by(UserInvitation.created_at.desc()).first()
    if latest and latest.last_attempt_at and latest.last_attempt_at > datetime.utcnow() - timedelta(seconds=60):
        logger.warning(
            "Firebase invitation resend rate limited company_id=%s user_id=%s invitation_id=%s",
            user.company_id, user.id, latest.id,
        )
        raise HTTPException(status_code=429, detail="Wait one minute before resending the invitation.")
    invitation = provision_invitation(db, user=user, invited_by_user_id=invited_by_user_id)
    if invitation.status == "delivery_failed":
        raise HTTPException(
            status_code=424,
            detail=f"Firebase did not accept the activation request: {invitation.last_error or 'unknown error'}",
        )
    if latest and latest.id != invitation.id and latest.status == "accepted_by_provider":
        latest.status = "revoked"
        latest.revoked_at = datetime.utcnow()
        db.commit()
        logger.info(
            "Previous Firebase invitation revoked after successful resend company_id=%s user_id=%s old_invitation_id=%s new_invitation_id=%s",
            user.company_id, user.id, latest.id, invitation.id,
        )
    return invitation


def set_user_enabled(db: Session, *, user: User, enabled: bool) -> None:
    user.is_active = enabled
    if enabled:
        user.auth_status = UserAuthStatus.ACTIVE if user.activated_at else UserAuthStatus.INVITED
    else:
        user.auth_status = UserAuthStatus.SUSPENDED
    # Black Penguin authorization is resolved from PostgreSQL on every request.
    # Firebase REST has no service-account operation for disabling identities.


def mark_invitation_accepted(db: Session, user: User) -> None:
    now = datetime.utcnow()
    user.auth_status = UserAuthStatus.ACTIVE
    user.is_active = True
    user.activated_at = user.activated_at or now
    user.last_login_at = now
    invitation = db.query(UserInvitation).filter(
        UserInvitation.user_id == user.id,
        UserInvitation.status.in_(["pending", "accepted_by_provider", "delivery_failed"]),
    ).order_by(UserInvitation.created_at.desc()).first()
    if invitation:
        invitation.status = "accepted"
        invitation.accepted_at = now
        invitation.provisioning_secret_ciphertext = None
    db.commit()
