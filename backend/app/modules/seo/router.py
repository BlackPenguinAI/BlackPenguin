from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from . import service

router = APIRouter()


def _response(item):
    return {"id": item.id, "target_url": item.target_url, "status": item.status, "score": item.score, "details": item.details, "created_at": item.created_at}


@router.get("/audits")
def list_audits(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return [_response(item) for item in service.audits(db)]


@router.post("/audits")
def create_audit(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return _response(service.run_audit(db))
