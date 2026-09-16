from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker, get_current_user
from app.modules.projects.models import Project
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users.project_access import require_project_access

from . import services
from .models import (
    AgentOperatingPolicy, ConversationKpiTarget, DataExportAuditEvent,
    KnowledgeGuidanceItem, Notification,
)
from .schemas import (
    AuditEventResponse, GuidanceItemPayload, GuidanceItemResponse,
    KpiTargetPayload, KpiTargetResponse, NotificationResponse,
    OperatingPolicyPayload, OperatingPolicyResponse,
)


router = APIRouter()


def _scope(db: Session, user: User, project_id: str | None) -> None:
    if not project_id:
        return
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == user.company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(db, user, project_id)


@router.get("/admin/export-audit", response_model=list[AuditEventResponse])
def export_audit(
    company_id: str | None = None, actor_user_id: str | None = None,
    export_type: str | None = None, limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    query = db.query(DataExportAuditEvent)
    if company_id: query = query.filter(DataExportAuditEvent.company_id == company_id)
    if actor_user_id: query = query.filter(DataExportAuditEvent.actor_user_id == actor_user_id)
    if export_type: query = query.filter(DataExportAuditEvent.export_type == export_type)
    return query.order_by(DataExportAuditEvent.created_at.desc()).limit(limit).all()


@router.get("/operating-policy", response_model=OperatingPolicyResponse | None)
def get_operating_policy(
    project_id: str | None = None, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _scope(db, current_user, project_id)
    return services.operating_policy_for(db, company_id=current_user.company_id, project_id=project_id)


@router.put("/operating-policy", response_model=OperatingPolicyResponse)
def put_operating_policy(
    payload: OperatingPolicyPayload, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _scope(db, current_user, payload.project_id)
    return services.upsert_operating_policy(db, user=current_user, payload=payload)


@router.get("/guidance", response_model=list[GuidanceItemResponse])
def list_guidance(
    project_id: str | None = None, include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _scope(db, current_user, project_id)
    query = db.query(KnowledgeGuidanceItem).filter(KnowledgeGuidanceItem.company_id == current_user.company_id)
    if project_id: query = query.filter((KnowledgeGuidanceItem.project_id == project_id) | (KnowledgeGuidanceItem.project_id.is_(None)))
    else: query = query.filter(KnowledgeGuidanceItem.project_id.is_(None))
    if not include_archived: query = query.filter(KnowledgeGuidanceItem.status != "archived")
    return query.order_by(KnowledgeGuidanceItem.updated_at.desc()).all()


@router.post("/guidance", response_model=GuidanceItemResponse, status_code=status.HTTP_201_CREATED)
def create_guidance(
    payload: GuidanceItemPayload, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _scope(db, current_user, payload.project_id)
    now = datetime.utcnow()
    item = KnowledgeGuidanceItem(
        company_id=current_user.company_id, created_by_user_id=current_user.id,
        approved_by_user_id=current_user.id if payload.status == "approved" else None,
        approved_at=now if payload.status == "approved" else None,
        **payload.model_dump(),
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.put("/guidance/{item_id}", response_model=GuidanceItemResponse)
def update_guidance(
    item_id: str, payload: GuidanceItemPayload, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    item = db.query(KnowledgeGuidanceItem).filter(
        KnowledgeGuidanceItem.id == item_id, KnowledgeGuidanceItem.company_id == current_user.company_id,
    ).first()
    if not item: raise HTTPException(status_code=404, detail="Guidance item not found.")
    _scope(db, current_user, payload.project_id)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    item.version += 1
    item.approved_by_user_id = current_user.id if payload.status == "approved" else None
    item.approved_at = datetime.utcnow() if payload.status == "approved" else None
    db.commit(); db.refresh(item)
    return item


@router.delete("/guidance/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_guidance(
    item_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    item = db.query(KnowledgeGuidanceItem).filter(
        KnowledgeGuidanceItem.id == item_id, KnowledgeGuidanceItem.company_id == current_user.company_id,
    ).first()
    if not item: raise HTTPException(status_code=404, detail="Guidance item not found.")
    item.status = "archived"; item.version += 1; db.commit()


@router.get("/kpis")
def kpis(
    project_id: str | None = None, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    _scope(db, current_user, project_id)
    return services.kpi_snapshot(db, company_id=current_user.company_id, project_id=project_id)


@router.put("/kpi-target", response_model=KpiTargetResponse)
def put_kpi_target(
    payload: KpiTargetPayload, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _scope(db, current_user, payload.project_id)
    item = db.query(ConversationKpiTarget).filter(
        ConversationKpiTarget.company_id == current_user.company_id,
        ConversationKpiTarget.project_id == payload.project_id,
    ).first() or ConversationKpiTarget(company_id=current_user.company_id, project_id=payload.project_id)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    item.updated_by_user_id = current_user.id
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/notifications", response_model=list[NotificationResponse])
def notifications(
    unread_only: bool = False, limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    services.process_notification_outbox(db, company_id=current_user.company_id)
    query = db.query(Notification).filter(Notification.recipient_user_id == current_user.id)
    if unread_only: query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    services.process_notification_outbox(db, company_id=current_user.company_id)
    return {"count": db.query(Notification).filter(
        Notification.recipient_user_id == current_user.id, Notification.read_at.is_(None),
    ).count()}


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    item = db.query(Notification).filter(
        Notification.id == notification_id, Notification.recipient_user_id == current_user.id,
    ).first()
    if not item: raise HTTPException(status_code=404, detail="Notification not found.")
    item.read_at = item.read_at or datetime.utcnow(); db.commit(); db.refresh(item)
    return item
