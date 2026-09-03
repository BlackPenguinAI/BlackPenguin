import os
import shutil
import logging
from fastapi import HTTPException, UploadFile
from datetime import datetime
from sqlalchemy.orm import Session

from app.integrations import firebase_admin_client
from app.modules.system_settings.services import get_firebase_config
from app.modules.users.models import User, UserAuthStatus

from .models import Company

UPLOAD_DIR = "uploads/receipts"
os.makedirs(UPLOAD_DIR, exist_ok=True)
logger = logging.getLogger(__name__)

def save_receipt_file(email: str, file: UploadFile) -> str:
    """Guarda el comprobante localmente y devuelve la URL."""
    file_ext = file.filename.split(".")[-1]
    new_filename = f"{email.split('@')[0]}_{int(datetime.utcnow().timestamp())}.{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, new_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return f"/uploads/receipts/{new_filename}"


def delete_company_workspace(
    db: Session,
    company: Company,
    *,
    confirm_manual_firebase_cleanup: bool = False,
    deleted_by_user_id: str | None = None,
) -> int:
    """Delete Firebase identities before discarding their local identifiers.

    The tenant is disabled first. If a provider call fails, a later request can
    retry safely because Firebase USER_NOT_FOUND is an idempotent success.

    An explicit manual-cleanup confirmation skips the remote call. This is a
    recovery path for administrators who already removed the identities in the
    Firebase console; it must never happen implicitly.
    """
    users = db.query(User).filter(User.company_id == company.id).order_by(User.id).all()
    firebase_config = None
    if users and not confirm_manual_firebase_cleanup:
        firebase_admin_client.ensure_admin_deletion_ready()
        firebase_config = get_firebase_config(db)
        if not firebase_config.project_id:
            raise HTTPException(status_code=409, detail="Firebase Project ID is required before deleting a Company.")

    if confirm_manual_firebase_cleanup and users:
        logger.warning(
            "Company local cascade authorized after manual Firebase cleanup "
            "company_id=%s deleted_by_user_id=%s user_count=%s users_with_firebase_uid=%s",
            company.id,
            deleted_by_user_id,
            len(users),
            sum(1 for user in users if user.firebase_uid),
        )

    company.is_active = False
    for user in users:
        user.is_active = False
        user.auth_status = UserAuthStatus.SUSPENDED
    db.commit()

    if not confirm_manual_firebase_cleanup and users:
        assert firebase_config is not None
        try:
            for user in users:
                firebase_admin_client.delete_identity(
                    project_id=firebase_config.project_id,
                    firebase_uid=user.firebase_uid,
                    email=user.email,
                )
        except HTTPException:
            # Keep the disabled tenant and its identifiers for a safe retry.
            raise

    db.delete(company)
    db.commit()
    return len(users)
