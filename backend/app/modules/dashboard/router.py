from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.company_onboarding.completion import calculate_completion as calculate_company_completion
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.projects.models import Project
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_crm.models import Lead, Meeting, MeetingStatus, SalesAvailabilityBlock, SmsChatMessage
from app.modules.users.models import SALES_ACTOR_ROLES, TENANT_MANAGER_ROLES, User, UserRole

from .schemas import DashboardStats, SetupProgress


router = APIRouter()
roles = [UserRole.ADMIN, UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES]


def _step_status(*, complete: bool, dependencies_complete: bool) -> str:
    if complete:
        return "complete"
    return "current" if dependencies_complete else "locked"


def _setup_progress(db: Session, user: User) -> dict:
    """Return the server-owned Company Administrator setup journey.

    The contract deliberately uses persisted tenant state instead of browser
    flags. Demo Projects and demo Leads never satisfy the production journey.
    """
    now = datetime.utcnow()
    company_profile = db.query(CompanyProfile).filter(
        CompanyProfile.company_id == user.company_id,
    ).first()
    company_complete = bool(company_profile and calculate_company_completion(
        company_profile.field_states,
        final_approved=company_profile.final_approved,
    )["can_complete"])

    projects = db.query(Project).filter(
        Project.company_id == user.company_id,
        Project.is_active.is_(True),
        Project.is_demo.is_(False),
    ).order_by(Project.created_at.asc()).all()
    completed_projects = [
        project for project in projects
        if project.onboarding_status == "completed"
        and project.profile is not None
        and project.profile.final_approved
    ]
    project_complete = bool(completed_projects)
    project = completed_projects[0] if completed_projects else (projects[0] if projects else None)
    project_url = (
        f"/app/projects/{project.id}/onboarding"
        if project and not project_complete
        else "/app/projects"
    )

    sales_actor_ids = [row[0] for row in db.query(User.id).filter(
        User.company_id == user.company_id,
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        User.role.in_(SALES_ACTOR_ROLES),
    ).all()]
    availability_complete = bool(sales_actor_ids) and db.query(SalesAvailabilityBlock.id).filter(
        SalesAvailabilityBlock.user_id.in_(sales_actor_ids),
        SalesAvailabilityBlock.ends_at > now,
    ).first() is not None

    completed_project_ids = [project.id for project in completed_projects]
    lead_complete = bool(completed_project_ids) and db.query(Lead.id).filter(
        Lead.company_id == user.company_id,
        Lead.project_id.in_(completed_project_ids),
        Lead.platform == "manual",
        Lead.is_demo.is_(False),
        Lead.deleted_at.is_(None),
    ).first() is not None

    facts = {
        "company": company_complete,
        "project": project_complete,
        "availability": availability_complete,
        "lead": lead_complete,
    }
    order = ["company", "project", "availability", "lead"]
    current_step = next((step for step in order if not facts[step]), "complete")
    project_query = f"?project={project.id}" if project and project_complete else ""
    urls = {
        "company": "/app/company/onboarding",
        "project": project_url,
        "availability": f"/app/schedule{project_query}",
        "lead": f"/app/agent?new=1{('&project=' + project.id) if project and project_complete else ''}",
    }
    labels = {
        "company": "Company Profile",
        "project": "First Project",
        "availability": "Available time slots",
        "lead": "First manual Lead",
    }
    details = {
        "company": "Complete and approve the Company Profile.",
        "project": "Create and approve the first non-demo Project.",
        "availability": "Create at least one future availability block for a Sales-capable user.",
        "lead": "Register the first manual Lead for an approved Project.",
    }
    steps = []
    dependencies_complete = True
    for step in order:
        complete = facts[step]
        steps.append({
            "id": step,
            "label": labels[step],
            "status": _step_status(complete=complete, dependencies_complete=dependencies_complete),
            "url": urls[step],
            "entity_id": project.id if step in {"project", "availability", "lead"} and project else None,
            "detail": details[step],
        })
        dependencies_complete = dependencies_complete and complete

    next_url = "/app/agent" if current_step == "complete" else urls[current_step]
    return {
        "current_step": current_step,
        "next_url": next_url,
        "is_complete": current_step == "complete",
        "steps": steps,
    }


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


@router.get("/setup-progress", response_model=SetupProgress)
def setup_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    return _setup_progress(db, current_user)


@router.get("/legacy-stats", response_model=DashboardStats, deprecated=True)
def legacy_dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(roles))):
    return _stats(db, current_user)
