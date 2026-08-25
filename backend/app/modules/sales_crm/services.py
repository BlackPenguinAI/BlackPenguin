from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime, timedelta

from .models import Lead, LeadStageHistory, SmsChatMessage, Meeting, MeetingAttachment, FunnelStage, MeetingStatus
from .schemas import LeadUpdate, MeetingCreate, MeetingUpdate
from app.modules.brokers.models import Broker
from app.modules.projects.models import Project
from app.modules.users.models import User, UserRole
from app.integrations.gcalendar_client import create_calendar_event

def get_project_leads(db: Session, company_id: str, project_id: str, sales_user_id: str | None = None) -> List[Lead]:
    query = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.project_id == project_id
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    return query.order_by(Lead.created_at.desc()).all()

def get_lead_sms_chat(
    db: Session, lead_id: str, company_id: str, sales_user_id: str | None = None,
) -> List[SmsChatMessage]:
    query = db.query(SmsChatMessage).join(Lead).filter(
        SmsChatMessage.lead_id == lead_id,
        Lead.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    return query.order_by(SmsChatMessage.created_at.asc()).all()


def get_lead_detail(db: Session, lead_id: str, company_id: str, sales_user_id: str | None = None) -> dict:
    from app.modules.projects.models import Project, ProjectCampaign
    from app.modules.sales_agent.models import SalesAgentSimulation, SalesConversation, SalesMessage

    query = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id)
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    lead = query.first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    project = db.query(Project).filter(Project.id == lead.project_id).first()
    campaign = db.query(ProjectCampaign).filter(ProjectCampaign.id == lead.campaign_id).first() if lead.campaign_id else None
    conversation = db.query(SalesConversation).filter(SalesConversation.lead_id == lead.id).first()
    simulation = db.query(SalesAgentSimulation).filter(SalesAgentSimulation.lead_id == lead.id).first()
    meta_form_data = lead.meta_form_data or (simulation.form_snapshot if simulation else {}) or {}
    messages = []
    if conversation:
        messages = db.query(SalesMessage).filter(
            SalesMessage.conversation_id == conversation.id,
        ).order_by(SalesMessage.created_at.asc()).limit(100).all()
    chat_summary = lead.qualification_summary
    if not chat_summary and messages:
        chat_summary = "Recent conversation: " + " | ".join(
            f"{message.role}: {message.content}" for message in reversed(messages)
        )
    recommendations = lead.visit_recommendations or (
        "Review the captured preferences, confirm any unresolved requirements and use the chat history "
        "to prepare a relevant property visit."
    )
    return {
        **{column.name: getattr(lead, column.name) for column in Lead.__table__.columns},
        "project_name": project.name if project else None,
        "campaign_name": campaign.name if campaign else None,
        "conversation_id": conversation.id if conversation else None,
        "meta_form_data": meta_form_data,
        "chat_summary": chat_summary,
        "visit_recommendations": recommendations,
        "chat_messages": [
            {"id": message.id, "role": message.role, "content": message.content, "created_at": message.created_at}
            for message in messages
        ] or [
            {"id": message.id, "role": message.role, "content": message.content, "created_at": message.created_at}
            for message in get_lead_sms_chat(db, lead.id, company_id, sales_user_id)
        ],
    }

def update_lead(db: Session, lead_id: str, company_id: str, payload: LeadUpdate, actor_id: str | None = None, sales_user_id: str | None = None) -> Lead:
    query = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id)
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    lead = query.first()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado.")
    
    previous = lead.funnel_stage.value if hasattr(lead.funnel_stage, "value") else str(lead.funnel_stage)
    lead.funnel_stage = payload.funnel_stage
    lead.stage_changed_at = datetime.utcnow()
    db.add(LeadStageHistory(
        lead_id=lead.id,
        from_stage=previous,
        to_stage=payload.funnel_stage.value,
        actor_type="user",
        actor_id=actor_id,
        reason="Manual CRM update",
    ))
    db.commit()
    db.refresh(lead)
    return lead

def _company_sales_user(db: Session, company_id: str, user_id: str | None) -> User | None:
    if not user_id:
        return None
    user = db.query(User).filter(
        User.id == user_id, User.company_id == company_id, User.role == UserRole.SALES,
        User.is_active.is_(True),
    ).first()
    if not user:
        raise HTTPException(status_code=422, detail="Assigned Sales user is invalid or inactive.")
    return user


def _ensure_meeting_slot_free(
    db: Session, *, sales_user_id: str | None, meeting_time: datetime,
    duration_minutes: int, exclude_meeting_id: str | None = None,
) -> None:
    if not sales_user_id:
        return
    starts_at = meeting_time.replace(tzinfo=None) if meeting_time.tzinfo else meeting_time
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    query = db.query(Meeting).filter(
        Meeting.assigned_sales_user_id == sales_user_id,
        Meeting.status.in_([MeetingStatus.SCHEDULED, MeetingStatus.CONFIRMED, MeetingStatus.IN_PROGRESS]),
        Meeting.meeting_time < ends_at,
    )
    if exclude_meeting_id:
        query = query.filter(Meeting.id != exclude_meeting_id)
    for existing in query.all():
        if existing.meeting_time + timedelta(minutes=existing.duration_minutes) > starts_at:
            raise HTTPException(status_code=409, detail="The Sales user already has an appointment in this time range.")


def create_meeting(db: Session, payload: MeetingCreate, company_id: str, assigned_sales_user_id: str | None = None) -> Meeting:
    lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.company_id == company_id).first()
    broker = None
    if payload.broker_id:
        broker = db.query(Broker).join(Project, Project.id == Broker.project_id).filter(
            Broker.id == payload.broker_id, Broker.project_id == payload.project_id,
            Project.company_id == company_id,
        ).first()
    project = db.query(Project).filter(Project.id == payload.project_id, Project.company_id == company_id).first()
    
    if not lead or not project or lead.project_id != project.id or (payload.broker_id and not broker):
        raise HTTPException(status_code=400, detail="Lead o Broker inválido.")
    if project.is_demo:
        raise HTTPException(status_code=409, detail="Demo Projects cannot create real meetings.")
        
    # Sincronización asíncrona / cliente Google Calendar
    gcal_id = None
    if broker and broker.google_calendar_id:
        gcal_id = create_calendar_event(
            calendar_id=broker.google_calendar_id,
            title=f"Meeting with {lead.full_name}",
            start_time=payload.meeting_time,
            attendee_email=lead.email or broker.email
        )

    target_sales_user_id = assigned_sales_user_id or payload.assigned_sales_user_id or lead.assigned_sales_user_id
    _company_sales_user(db, company_id, target_sales_user_id)
    _ensure_meeting_slot_free(
        db, sales_user_id=target_sales_user_id, meeting_time=payload.meeting_time,
        duration_minutes=payload.duration_minutes,
    )
    meeting = Meeting(
        project_id=payload.project_id,
        lead_id=payload.lead_id,
        broker_id=payload.broker_id,
        assigned_sales_user_id=target_sales_user_id,
        meeting_time=payload.meeting_time,
        duration_minutes=payload.duration_minutes,
        modality=payload.modality,
        notes=payload.notes,
        status=MeetingStatus.SCHEDULED,
        gcal_event_id=gcal_id
    )
    db.add(meeting)
    
    # Actualizamos la etapa del lead a cita agendada
    previous_stage = lead.funnel_stage.value if hasattr(lead.funnel_stage, "value") else str(lead.funnel_stage)
    lead.funnel_stage = FunnelStage.APPOINTMENT_SET
    lead.stage_changed_at = datetime.utcnow()
    db.add(LeadStageHistory(
        lead_id=lead.id,
        from_stage=previous_stage,
        to_stage=FunnelStage.APPOINTMENT_SET.value,
        actor_type="system",
        actor_id=assigned_sales_user_id,
        reason="Meeting created",
    ))
    
    db.commit()
    db.refresh(meeting)
    return meeting

def get_project_meetings(db: Session, company_id: str, project_id: str, broker_id: Optional[str] = None, sales_user_id: str | None = None) -> List[Meeting]:
    query = db.query(Meeting).join(Project, Project.id == Meeting.project_id).filter(
        Meeting.project_id == project_id,
        Project.company_id == company_id,
    )
    if broker_id:
        query = query.filter(Meeting.broker_id == broker_id)
    if sales_user_id:
        query = query.filter(Meeting.assigned_sales_user_id == sales_user_id)
    return query.order_by(Meeting.meeting_time.asc()).all()


def get_tenant_meeting(db: Session, meeting_id: str, company_id: str, sales_user_id: str | None = None) -> Meeting:
    query = db.query(Meeting).join(Project, Project.id == Meeting.project_id).filter(
        Meeting.id == meeting_id, Project.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Meeting.assigned_sales_user_id == sales_user_id)
    meeting = query.first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting

def update_meeting(db: Session, meeting_id: str, company_id: str, payload: MeetingUpdate, sales_user_id: str | None = None) -> Meeting:
    meeting = get_tenant_meeting(db, meeting_id, company_id, sales_user_id)
    updates = payload.model_dump(exclude_unset=True)
    if "assigned_sales_user_id" in updates:
        _company_sales_user(db, company_id, updates["assigned_sales_user_id"])
    if updates.get("broker_id"):
        broker = db.query(Broker).filter(Broker.id == updates["broker_id"], Broker.project_id == meeting.project_id).first()
        if not broker:
            raise HTTPException(status_code=400, detail="Broker is not assigned to this Project.")
    requested_status = updates.get("status")
    effective_status = requested_status or meeting.status
    proposed_sales_user_id = updates.get("assigned_sales_user_id", meeting.assigned_sales_user_id)
    proposed_time = updates.get("meeting_time", meeting.meeting_time)
    proposed_duration = updates.get("duration_minutes", meeting.duration_minutes)
    _ensure_meeting_slot_free(
        db, sales_user_id=proposed_sales_user_id, meeting_time=proposed_time,
        duration_minutes=proposed_duration, exclude_meeting_id=meeting.id,
    )
    if any(updates.get(field) for field in ("visit_notes", "visit_details", "sale_closed_at")) and effective_status not in {
        MeetingStatus.IN_PROGRESS, MeetingStatus.COMPLETED, MeetingStatus.COMPLETED_SALE_PENDING, MeetingStatus.SALE_CLOSED,
    }:
        raise HTTPException(status_code=409, detail="Start the visit before saving its report.")
    if requested_status and requested_status != meeting.status:
        allowed = {
            MeetingStatus.SCHEDULED: {MeetingStatus.CONFIRMED, MeetingStatus.IN_PROGRESS, MeetingStatus.CANCELLED, MeetingStatus.NO_SHOW},
            MeetingStatus.CONFIRMED: {MeetingStatus.IN_PROGRESS, MeetingStatus.CANCELLED, MeetingStatus.NO_SHOW},
            MeetingStatus.IN_PROGRESS: {MeetingStatus.COMPLETED, MeetingStatus.COMPLETED_SALE_PENDING, MeetingStatus.SALE_CLOSED},
            MeetingStatus.COMPLETED_SALE_PENDING: {MeetingStatus.SALE_CLOSED},
        }
        if requested_status not in allowed.get(meeting.status, set()):
            raise HTTPException(status_code=409, detail=f"Meeting cannot move from {meeting.status.value} to {requested_status.value}.")
        now = datetime.utcnow()
        if requested_status == MeetingStatus.SALE_CLOSED:
            closing_date = updates.get("sale_closed_at")
            evidence = db.query(MeetingAttachment).filter(
                MeetingAttachment.meeting_id == meeting.id,
                MeetingAttachment.kind == "sale_evidence",
            ).first()
            if not closing_date or not evidence:
                raise HTTPException(status_code=422, detail="Sale evidence and closing date are required to close a sale.")
        if requested_status == MeetingStatus.IN_PROGRESS:
            meeting.started_at = meeting.started_at or now
        if requested_status in {MeetingStatus.COMPLETED, MeetingStatus.COMPLETED_SALE_PENDING, MeetingStatus.SALE_CLOSED}:
            meeting.completed_at = meeting.completed_at or now
        if requested_status == MeetingStatus.SALE_CLOSED:
            previous_stage = meeting.lead.funnel_stage.value
            meeting.lead.funnel_stage = FunnelStage.CLOSED
            meeting.lead.stage_changed_at = now
            db.add(LeadStageHistory(
                lead_id=meeting.lead.id, from_stage=previous_stage, to_stage=FunnelStage.CLOSED.value,
                actor_type="user", actor_id=sales_user_id, reason="Sale closed from property visit",
            ))
    for field, value in updates.items():
        setattr(meeting, field, value)
    db.add(meeting); db.commit(); db.refresh(meeting)
    return meeting


def delete_meeting(db: Session, meeting_id: str, company_id: str) -> None:
    meeting = get_tenant_meeting(db, meeting_id, company_id)
    if meeting.status in {MeetingStatus.IN_PROGRESS, MeetingStatus.SALE_CLOSED}:
        raise HTTPException(status_code=409, detail="An in-progress or closed-sale appointment cannot be deleted.")
    db.delete(meeting); db.commit()
