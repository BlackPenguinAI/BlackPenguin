from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_invitation_state,
    verify_password,
)
from app.db.postgres import get_db
from app.integrations import firebase_client
from app.modules.auth.deps import get_current_user
from app.modules.system_settings.services import get_firebase_config
from app.modules.users import services as user_services
from app.modules.users.models import User, UserAuthStatus, UserInvitation

from .schemas import TokenResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class FirebaseActionCodePayload(BaseModel):
    state: str = Field(min_length=20, max_length=4096)


class CompleteInvitationPayload(FirebaseActionCodePayload):
    oob_code: str = Field(min_length=8, max_length=2048)
    new_password: str = Field(min_length=10, max_length=128)


class ForgotPasswordPayload(BaseModel):
    email: EmailStr


class FirebaseExchangePayload(BaseModel):
    id_token: str = Field(min_length=20)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


def _session_response(user: User) -> dict:
    user.last_login_at = datetime.utcnow()
    token = create_access_token(data={
        "sub": user.email, "role": user.role, "company_id": user.company_id,
        "firebase_uid": user.firebase_uid,
    })
    return {
        "access_token": token, "token_type": "bearer", "role": user.role,
        "name": user.first_name or "User",
    }


@router.post("/login", response_model=TokenResponse, summary="Sign in")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form_data.username.strip().casefold()
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or user.auth_status == UserAuthStatus.SUSPENDED:
        raise HTTPException(status_code=400, detail="Email or password is incorrect.")
    if user.auth_status in {UserAuthStatus.INVITED, UserAuthStatus.PROVISIONING_FAILED}:
        raise HTTPException(status_code=409, detail="Activate your account from the invitation email before signing in.")

    config = get_firebase_config(db)
    authenticated = False
    if config.is_enabled and user.firebase_uid:
        firebase_session = firebase_client.sign_in_with_password(db, email, form_data.password)
        if firebase_session.get("localId") != user.firebase_uid:
            raise HTTPException(status_code=401, detail="Firebase identity does not match this Black Penguin account.")
        authenticated = True
    elif config.is_enabled and (config.auth_mode or "hybrid") == "hybrid":
        if verify_password(form_data.password, user.hashed_password):
            try:
                identity = firebase_client.create_identity(
                    db, email=user.email,
                    display_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
                    password=form_data.password,
                )
                user.firebase_uid = identity.uid
                authenticated = True
            except HTTPException:
                # Hybrid mode preserves access while a legacy identity is reconciled.
                user.auth_status = UserAuthStatus.MIGRATION_REQUIRED
                authenticated = True
    else:
        authenticated = verify_password(form_data.password, user.hashed_password)

    if not authenticated:
        raise HTTPException(status_code=400, detail="Email or password is incorrect.")
    response = _session_response(user)
    db.commit()
    return response


def _pending_invitation_from_state(state_token: str, db: Session) -> tuple[User, UserInvitation]:
    state = verify_invitation_state(state_token)
    if not state:
        raise HTTPException(status_code=410, detail="This invitation is invalid or expired.")
    invitation = db.query(UserInvitation).filter(
        UserInvitation.id == state["invitation_id"],
        UserInvitation.user_id == state["sub"],
        UserInvitation.status.in_(["pending", "accepted_by_provider", "delivery_failed"]),
        UserInvitation.expires_at > datetime.utcnow(),
    ).first()
    if not invitation:
        raise HTTPException(status_code=410, detail="This invitation is expired or no longer active.")
    user = db.query(User).filter(User.id == invitation.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Invitation account was not found.")
    if user.auth_status == UserAuthStatus.SUSPENDED or not user.is_active:
        raise HTTPException(status_code=410, detail="This invitation is expired or no longer active.")
    if user.auth_status not in {UserAuthStatus.INVITED, UserAuthStatus.PROVISIONING_FAILED}:
        raise HTTPException(status_code=409, detail="This account has already been activated.")
    return user, invitation


@router.post("/firebase/action-code")
def inspect_firebase_action(payload: FirebaseActionCodePayload, db: Session = Depends(get_db)):
    user, _ = _pending_invitation_from_state(payload.state, db)
    return {
        "email": user.email, "first_name": user.first_name, "role": user.role,
        "company_name": user.company.name if user.company else None, "flow": "invitation",
    }


@router.post("/firebase/complete-invitation", response_model=TokenResponse)
def complete_firebase_invitation(payload: CompleteInvitationPayload, db: Session = Depends(get_db)):
    user, _ = _pending_invitation_from_state(payload.state, db)
    firebase_session = firebase_client.sign_in_with_email_link(
        db, email=user.email, oob_code=payload.oob_code,
    )
    firebase_uid = firebase_session.get("localId")
    id_token = firebase_session.get("idToken")
    if not firebase_uid or not id_token:
        raise HTTPException(status_code=502, detail="Firebase returned an incomplete activation response.")
    linked_user = db.query(User).filter(
        User.firebase_uid == firebase_uid,
        User.id != user.id,
    ).first()
    if linked_user:
        raise HTTPException(status_code=409, detail="Firebase identity is already linked to another account.")
    if user.firebase_uid and user.firebase_uid != firebase_uid:
        logger.warning(
            "Rebinding pending invitation to verified Firebase identity company_id=%s user_id=%s old_uid=%s new_uid=%s",
            user.company_id, user.id, user.firebase_uid, firebase_uid,
        )
    firebase_client.update_password(db, id_token=id_token, password=payload.new_password)
    user.firebase_uid = firebase_uid
    user.hashed_password = get_password_hash(payload.new_password)
    user_services.mark_invitation_accepted(db, user)
    response = _session_response(user)
    db.commit()
    return response


@router.post("/firebase/exchange", response_model=TokenResponse)
def exchange_firebase_token(payload: FirebaseExchangePayload, db: Session = Depends(get_db)):
    identity = firebase_client.verify_id_token(db, payload.id_token)
    user = db.query(User).filter(User.firebase_uid == identity.get("uid")).first()
    if not user or not user.is_active or user.auth_status != UserAuthStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Black Penguin account is not active.")
    response = _session_response(user)
    db.commit()
    return response


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(payload.email).casefold()).first()
    if user and user.firebase_uid and user.is_active:
        try:
            firebase_client.send_password_reset_email(db, user.email)
        except HTTPException:
            pass
    return {"detail": "If the account is eligible, password instructions have been sent."}


@router.put("/change-password/", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the signed-in user's credential without bypassing Firebase."""
    config = get_firebase_config(db)
    if config.is_enabled and current_user.firebase_uid:
        session = firebase_client.sign_in_with_password(db, current_user.email, payload.current_password)
        if session.get("localId") != current_user.firebase_uid:
            raise HTTPException(status_code=401, detail="Firebase identity does not match this Black Penguin account.")
        firebase_client.update_password(
            db, id_token=session["idToken"], password=payload.new_password,
        )
    elif not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    # Keep a valid fallback hash during the configured hybrid migration period.
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"detail": "Password updated successfully."}
