from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User

from .router import _stats, roles
from .schemas import DashboardStats

router = APIRouter()

@router.get("/dashboard-stats", response_model=DashboardStats, deprecated=True)
def legacy_tenant_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)
