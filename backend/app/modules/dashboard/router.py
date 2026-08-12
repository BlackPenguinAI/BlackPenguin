from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead, SmsChatMessage
from app.modules.users.models import User, UserRole

from .schemas import DashboardStats


router = APIRouter()
roles = [UserRole.ADMIN, UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES]


def _stats(db: Session, user: User) -> dict:
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    projects = db.query(Project).filter(Project.company_id == user.company_id, Project.is_active.is_(True)).count()
    leads = db.query(Lead).filter(Lead.company_id == user.company_id, Lead.created_at >= month_start).count()
    interactions = db.query(SmsChatMessage).join(Lead).filter(
        Lead.company_id == user.company_id,
        SmsChatMessage.role == "assistant",
        SmsChatMessage.created_at >= month_start,
    ).count()
    return {
        "projects": {"active": projects},
        "leads": {"current_month": leads},
        "ai_interactions": {"current_month": interactions},
        "generated_at": now,
        "projects_count": projects,
        "leads_count": leads,
        "ai_interactions_count": interactions,
    }


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)


@router.get("/legacy-stats", response_model=DashboardStats, deprecated=True)
def legacy_dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)
