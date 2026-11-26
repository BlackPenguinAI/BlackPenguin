"""Read-only, tenant-bounded multi-project opportunity discovery.

A phone identifies a Company contact, not a global buyer identity. Each Lead
remains a distinct opportunity with its own Project, bookings and state.
This helper never returns messages or active offers; the engine must switch
explicitly to a validated (company_id, project_id, lead_id) before dialogue.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead, Meeting


def company_opportunities(db: Session, *, company_id: str, phone: str) -> list[dict]:
    digits = ''.join(ch for ch in phone or '' if ch.isdigit())
    if not digits:
        return []
    db_phone = Lead.phone
    for char in ('+', ' ', '-', '(', ')'):
        db_phone = func.replace(db_phone, char, '')
    query = (db.query(Lead, Project)
        .join(Project, Project.id == Lead.project_id)
        .filter(Lead.company_id == company_id, Project.company_id == company_id,
                Lead.deleted_at.is_(None), db_phone == digits)
        .order_by(Lead.created_at.desc(), Lead.id))
    result = []
    for lead, project in query.all():
        # No other tenant, draft details, raw dialogue, calendar secrets,
        # earlier booking offers or reactivated historical message metadata.
        appointment_count = (db.query(Meeting.id).filter(
            Meeting.lead_id == lead.id, Meeting.project_id == project.id,
        ).count())
        result.append({
            'company_id': company_id,
            'project_id': project.id,
            'project_name': project.name,
            'lead_id': lead.id,
            'agent_status': lead.agent_status,
            'pipeline_stage': lead.pipeline_stage,
            'last_interaction_at': (lead.last_interaction_at.isoformat()
                                     if lead.last_interaction_at else None),
            'appointment_count': appointment_count,
        })
    return result
