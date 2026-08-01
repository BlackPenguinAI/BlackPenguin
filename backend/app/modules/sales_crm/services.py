from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime

from .models import Lead, SmsChatMessage, Meeting, FunnelStage, MeetingStatus
from .schemas import LeadUpdate, MeetingCreate
from app.modules.brokers.models import Broker
from app.integrations.gcalendar_client import create_calendar_event

def get_project_leads(db: Session, company_id: str, project_id: str) -> List[Lead]:
    return db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.project_id == project_id
    ).order_by(Lead.created_at.desc()).all()

def get_lead_sms_chat(db: Session, lead_id: str) -> List[SmsChatMessage]:
    return db.query(SmsChatMessage).filter(
        SmsChatMessage.lead_id == lead_id
    ).order_by(SmsChatMessage.created_at.asc()).all()

def update_lead(db: Session, lead_id: str, company_id: str, payload: LeadUpdate) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado.")
    
    lead.funnel_stage = payload.funnel_stage
    db.commit()
    db.refresh(lead)
    return lead

def create_meeting(db: Session, payload: MeetingCreate) -> Meeting:
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    broker = db.query(Broker).filter(Broker.id == payload.broker_id).first()
    
    if not lead or not broker:
        raise HTTPException(status_code=400, detail="Lead o Broker inválido.")
        
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
        meeting_time=payload.meeting_time,
        status=MeetingStatus.SCHEDULED,
        gcal_event_id=gcal_id
    )
    db.add(meeting)
    
    # Actualizamos la etapa del lead a cita agendada
    lead.funnel_stage = FunnelStage.APPOINTMENT_SET
    
    db.commit()
    db.refresh(meeting)
    return meeting

def get_project_meetings(db: Session, project_id: str, broker_id: Optional[str] = None) -> List[Meeting]:
    query = db.query(Meeting).filter(Meeting.project_id == project_id)
    if broker_id:
        query = query.filter(Meeting.broker_id == broker_id)
    return query.order_by(Meeting.meeting_time.asc()).all()