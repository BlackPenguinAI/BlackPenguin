from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime

from .models import Lead, LeadStageHistory, SmsChatMessage, Meeting, FunnelStage, MeetingStatus
from .schemas import LeadUpdate, MeetingCreate, MeetingUpdate
from app.modules.brokers.models import Broker
from app.modules.projects.models import Project
from app.integrations.gcalendar_client import create_calendar_event

def get_project_leads(db: Session, company_id: str, project_id: str, sales_user_id: str | None = None) -> List[Lead]:
    query = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.project_id == project_id
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    return query.order_by(Lead.created_at.desc()).all()

def get_lead_sms_chat(db: Session, lead_id: str, company_id: str) -> List[SmsChatMessage]:
    return db.query(SmsChatMessage).join(Lead).filter(
        SmsChatMessage.lead_id == lead_id,
        Lead.company_id == company_id,
    ).order_by(SmsChatMessage.created_at.asc()).all()

def update_lead(db: Session, lead_id: str, company_id: str, payload: LeadUpdate, actor_id: str | None = None) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
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

def create_meeting(db: Session, payload: MeetingCreate, company_id: str, assigned_sales_user_id: str | None = None) -> Meeting:
    lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.company_id == company_id).first()
    broker = db.query(Broker).join(Project, Project.id == Broker.project_id).filter(
        Broker.id == payload.broker_id,
        Broker.project_id == payload.project_id,
        Project.company_id == company_id,
    ).first()
    project = db.query(Project).filter(Project.id == payload.project_id, Project.company_id == company_id).first()
    
    if not lead or not broker or not project or lead.project_id != project.id:
        raise HTTPException(status_code=400, detail="Lead o Broker inválido.")
    if project.is_demo:
        raise HTTPException(status_code=409, detail="Demo Projects cannot create real meetings.")
        
    # Sincronización asíncrona / cliente Google Calendar
    gcal_id = None
    if broker.google_calendar_id:
        gcal_id = create_calendar_event(
            calendar_id=broker.google_calendar_id,
            title=f"Meeting with {lead.full_name}",
            start_time=payload.meeting_time,
            attendee_email=lead.email or broker.email
        )

    meeting = Meeting(
        project_id=payload.project_id,
        lead_id=payload.lead_id,
        broker_id=payload.broker_id,
        assigned_sales_user_id=assigned_sales_user_id or lead.assigned_sales_user_id,
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

def update_meeting(db: Session, meeting_id: str, company_id: str, payload: MeetingUpdate) -> Meeting:
    meeting = db.query(Meeting).join(Project, Project.id == Meeting.project_id).filter(
        Meeting.id == meeting_id, Project.company_id == company_id,
    ).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("broker_id"):
        broker = db.query(Broker).filter(Broker.id == updates["broker_id"], Broker.project_id == meeting.project_id).first()
        if not broker:
            raise HTTPException(status_code=400, detail="Broker is not assigned to this Project.")
    for field, value in updates.items():
        setattr(meeting, field, value)
    db.add(meeting); db.commit(); db.refresh(meeting)
    return meeting
