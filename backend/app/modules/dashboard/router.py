from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.projects.models import Project
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_crm.models import Lead, Meeting, MeetingStatus, SmsChatMessage
from app.modules.users.models import User, UserRole

from .schemas import DashboardStats


router = APIRouter()
roles = [UserRole.ADMIN, UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES]


def _stats(db: Session, user: User) -> dict:
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    projects = db.query(Project).filter(Project.company_id == user.company_id, Project.is_active.is_(True)).count()
    lead_query = db.query(Lead).filter(Lead.company_id == user.company_id, Lead.created_at >= month_start)
    if user.role == UserRole.SALES:
        lead_query = lead_query.filter(Lead.assigned_sales_user_id == user.id)
    leads = lead_query.count()
    if user.role == UserRole.SALES:
        interactions = db.query(SalesMessage).join(SalesConversation).join(Lead).filter(
            Lead.company_id == user.company_id,
            Lead.assigned_sales_user_id == user.id,
            SalesMessage.created_at >= month_start,
        ).count()
    else:
        interactions = db.query(SmsChatMessage).join(Lead).filter(
            Lead.company_id == user.company_id,
            SmsChatMessage.role == "assistant",
            SmsChatMessage.created_at >= month_start,
        ).count()
    result = {
        "projects": {"active": projects},
        "leads": {"current_month": leads},
        "ai_interactions": {"current_month": interactions},
        "generated_at": now,
        "projects_count": projects,
        "leads_count": leads,
        "ai_interactions_count": interactions,
    }
    if user.role == UserRole.SALES:
        today_start = datetime(now.year, now.month, now.day)
        today_end = today_start.replace(hour=23, minute=59, second=59)
        meeting_query = db.query(Meeting).filter(Meeting.assigned_sales_user_id == user.id)
        result["sales"] = {
            "assigned_leads": db.query(Lead).filter(Lead.assigned_sales_user_id == user.id).count(),
            "appointments_today": meeting_query.filter(
                Meeting.meeting_time >= today_start, Meeting.meeting_time <= today_end,
                Meeting.status.in_([MeetingStatus.SCHEDULED, MeetingStatus.CONFIRMED]),
            ).count(),
            "upcoming_appointments": db.query(Meeting).filter(
                Meeting.assigned_sales_user_id == user.id,
                Meeting.meeting_time >= now,
                Meeting.status.in_([MeetingStatus.SCHEDULED, MeetingStatus.CONFIRMED]),
            ).count(),
        }
    return result


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)


@router.get("/legacy-stats", response_model=DashboardStats, deprecated=True)
def legacy_dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)
