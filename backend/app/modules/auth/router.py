from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.postgres import get_db
from app.integrations import firebase_client
from app.modules.auth.deps import get_current_user
from app.modules.system_settings.services import get_firebase_config
from app.modules.users import services as user_services
from app.modules.users.models import User, UserAuthStatus, UserInvitation

from .schemas import TokenResponse

router = APIRouter()


class FirebaseActionCodePayload(BaseModel):
    oob_code: str = Field(min_length=8, max_length=2048)


class CompleteInvitationPayload(FirebaseActionCodePayload):
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


@router.post("/firebase/action-code")
def inspect_firebase_action(payload: FirebaseActionCodePayload, db: Session = Depends(get_db)):
    email = firebase_client.verify_password_action_code(db, payload.oob_code)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Invitation account was not found.")
    if user.auth_status == UserAuthStatus.SUSPENDED or not user.is_active:
        raise HTTPException(status_code=410, detail="This invitation is expired or no longer active.")
    invitation = None
    flow = "password_reset"
    if user.auth_status in {UserAuthStatus.INVITED, UserAuthStatus.PROVISIONING_FAILED}:
        invitation = db.query(UserInvitation).filter(
            UserInvitation.user_id == user.id,
            UserInvitation.status.in_(["pending", "accepted_by_provider", "delivery_failed"]),
            UserInvitation.expires_at > datetime.utcnow(),
        ).order_by(UserInvitation.created_at.desc()).first()
        if not invitation:
            raise HTTPException(status_code=410, detail="This invitation is expired or no longer active.")
        flow = "invitation"
    return {
        "email": user.email, "first_name": user.first_name, "role": user.role,
        "company_name": user.company.name if user.company else None, "flow": flow,
    }


@router.post("/firebase/complete-invitation", response_model=TokenResponse)
def complete_firebase_invitation(payload: CompleteInvitationPayload, db: Session = Depends(get_db)):
    preview = inspect_firebase_action(FirebaseActionCodePayload(oob_code=payload.oob_code), db)
    email = firebase_client.confirm_password_action(db, payload.oob_code, payload.new_password)
    if email != preview["email"]:
        raise HTTPException(status_code=409, detail="Invitation identity mismatch.")
    user = db.query(User).filter(User.email == email).first()
    firebase_session = firebase_client.sign_in_with_password(db, email, payload.new_password)
    if not user.firebase_uid or firebase_session.get("localId") != user.firebase_uid:
        raise HTTPException(status_code=409, detail="Firebase identity mismatch.")
    if preview["flow"] == "invitation":
        user_services.mark_invitation_accepted(db, user)
    else:
        user.auth_status = UserAuthStatus.ACTIVE
        user.is_active = True
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
            firebase_client.send_password_action_email(db, user.email)
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
