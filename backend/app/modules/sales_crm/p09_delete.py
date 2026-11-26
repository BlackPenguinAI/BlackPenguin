"""P09 guarded, tenant-scoped physical deletion of isolated sales opportunities.

Only the platform SUPERADMIN may invoke these routes. This module deliberately
rejects legacy physical threads shared by multiple opportunities, in-flight
provider work, and unreconciled Google Calendar events: deleting the parent
would otherwise erase another Project's conversation or leave live side effects.
No implicit bulk deletion by phone or across Companies is permitted.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.governance.schemas import DeletePayload
from app.modules.governance.services import record_platform_event
from app.modules.governance.models import Notification, NotificationOutbox
from app.modules.sales_crm.models import Lead, LeadContact, Meeting, MeetingAttachment
from app.modules.sales_crm import storage_service
from app.modules.sales_agent.models import (
    SalesConversation, SalesConversationLeadContext, SalesMessage, AgentRun,
    SalesInboundJob, SalesFollowUpJob, OutboundMessage, ExternalWebhookEvent,
)

router = APIRouter()


def _enabled() -> None:
    # Opt-in only after a real PostgreSQL migration and externally reconciled
    # Google Calendar / provider receipts have been verified by the operator.
    if os.getenv('BP_P09_HARD_DELETE_ENABLED', '').strip().lower() != 'true':
        raise HTTPException(409, detail={
            'code': 'P09_HARD_DELETE_NOT_ACTIVATED',
            'message': 'The guarded P09 hard-delete lane requires explicit activation after acceptance.',
        })


def _contact_leads(db: Session, company_id: str, contact: LeadContact) -> list[Lead]:
    # Some older leads were created before ensure_contact populated contact_id.
    # Phone comparison is scoped strictly to this Company, never globally.
    from sqlalchemy import func
    normalized = Lead.phone
    for ch in ('+', ' ', '-', '(', ')'):
        normalized = func.replace(normalized, ch, '')
    digits = ''.join(ch for ch in contact.canonical_phone if ch.isdigit())
    return db.query(Lead).filter(
        Lead.company_id == company_id,
        or_(Lead.contact_id == contact.id, normalized == digits),
    ).with_for_update().order_by(Lead.id).all()


def _conversations_for(db: Session, lead: Lead) -> list[SalesConversation]:
    historical_ids = db.query(SalesConversationLeadContext.conversation_id).filter(
        SalesConversationLeadContext.lead_id == lead.id,
    )
    return db.query(SalesConversation).filter(
        SalesConversation.company_id == lead.company_id,
        or_(SalesConversation.lead_id == lead.id, SalesConversation.id.in_(historical_ids)),
    ).with_for_update().order_by(SalesConversation.id).all()


def _preflight(db: Session, lead: Lead) -> tuple[list[SalesConversation], list[Meeting], list[str]]:
    conversations = _conversations_for(db, lead)
    blockers: list[str] = []
    for conversation in conversations:
        if conversation.lead_id != lead.id:
            blockers.append('SHARED_OR_HISTORICAL_PROVIDER_THREAD')
            continue
        other = db.query(SalesConversationLeadContext.id).filter(
            SalesConversationLeadContext.conversation_id == conversation.id,
            SalesConversationLeadContext.lead_id != lead.id,
        ).first()
        if other:
            blockers.append('SHARED_OR_HISTORICAL_PROVIDER_THREAD')
        active_inbound = db.query(SalesInboundJob.id).filter(
            SalesInboundJob.conversation_id == conversation.id,
            SalesInboundJob.status == 'processing',
        ).first()
        active_followup = db.query(SalesFollowUpJob.id).filter(
            SalesFollowUpJob.conversation_id == conversation.id,
            SalesFollowUpJob.status == 'processing',
        ).first()
        active_outbound = db.query(OutboundMessage.id).filter(
            OutboundMessage.conversation_id == conversation.id,
            OutboundMessage.status.in_(['sending', 'processing']),
        ).first()
        active_run = db.query(AgentRun.id).filter(
            AgentRun.conversation_id == conversation.id, AgentRun.status == 'running',
        ).first()
        if any((active_inbound, active_followup, active_outbound, active_run)):
            blockers.append('IN_FLIGHT_OPERATION')
    meetings = db.query(Meeting).filter(Meeting.lead_id == lead.id).with_for_update().all()
    if any(m.gcal_event_id for m in meetings):
        blockers.append('EXTERNAL_CALENDAR_RECONCILIATION_REQUIRED')
    return conversations, meetings, sorted(set(blockers))


def preview(db: Session, *, company_id: str, lead_id: str) -> dict:
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
    if not lead:
        raise HTTPException(404, 'Lead not found within Company.')
    conversations, meetings, blockers = _preflight(db, lead)
    count = sum(db.query(SalesMessage.id).filter(SalesMessage.conversation_id == c.id).count() for c in conversations)
    return {
        'company_id': company_id, 'lead_id': lead.id, 'project_id': lead.project_id,
        'conversations': len(conversations), 'messages_in_physical_threads': count,
        'meetings': len(meetings), 'blockers': blockers,
        'can_delete': not blockers,
        'warning': 'Physical thread counts may include another Project; any shared thread is blocked.',
    }


def _purge_one(db: Session, *, lead: Lead, actor: User, reason: str,
               request: Request) -> list[str]:
    conversations, meetings, blockers = _preflight(db, lead)
    if blockers:
        raise HTTPException(409, detail={'code': 'P09_DELETE_BLOCKED', 'blockers': blockers,
            'message': 'Resolve shared conversations, in-flight work and Calendar events before physical deletion.'})
    conversation_ids = [c.id for c in conversations]
    meeting_ids = [m.id for m in meetings]
    attachment_paths = ([path for (path,) in db.query(MeetingAttachment.storage_path).filter(
        MeetingAttachment.meeting_id.in_(meeting_ids),
    ).all()] if meeting_ids else [])
    # Revoke all queued messages before the physical erase. A concurrently
    # executing sender must also enforce scope at its own dispatch boundary.
    if conversation_ids:
        db.query(OutboundMessage).filter(
            OutboundMessage.conversation_id.in_(conversation_ids),
            OutboundMessage.status.in_(['draft', 'pending', 'queued', 'retry', 'scheduled']),
        ).update({'status': 'cancelled', 'last_error': 'Lead deleted'}, synchronize_session=False)
        db.query(SalesFollowUpJob).filter(
            SalesFollowUpJob.conversation_id.in_(conversation_ids),
            SalesFollowUpJob.status.in_(['pending', 'retry', 'scheduled']),
        ).update({'status': 'cancelled'}, synchronize_session=False)
    # Provider receipts must remain idempotent to prevent delayed webhook
    # replays from being attached to a future lead at the same phone number.
    # Remove private payloads from the retained deduplication tombstones.
    keys = set()
    if conversation_ids:
        for row in db.query(SalesMessage.metadata_json).filter(
            SalesMessage.conversation_id.in_(conversation_ids),
        ).all():
            meta = row[0] or {}
            provider, key = meta.get('provider'), meta.get('webhook_event_id')
            if provider in {'twilio', 'telnyx'} and isinstance(key, str) and key:
                keys.add((provider, key))
    if lead.platform == 'meta' and lead.external_lead_id:
        keys.add(('meta', lead.external_lead_id))
    for platform, event_id in keys:
        db.query(ExternalWebhookEvent).filter(
            ExternalWebhookEvent.platform == platform,
            ExternalWebhookEvent.external_event_id == event_id,
        ).update({'payload_json': {'p09_tombstone': True}, 'status': 'purged',
                  'error_message': None}, synchronize_session=False)
    # Notifications and queued bodies may contain the original name. Never
    # touch another tenant's notifications or shared team scheduling.
    db.query(Notification).filter(Notification.company_id == lead.company_id,
        Notification.entity_type == 'lead', Notification.entity_id == lead.id,
    ).delete(synchronize_session=False)
    db.query(NotificationOutbox).filter(NotificationOutbox.company_id == lead.company_id,
        NotificationOutbox.entity_type == 'lead', NotificationOutbox.entity_id == lead.id,
    ).delete(synchronize_session=False)
    # Immutable platform audit contains identifiers/hashes only, not dialogue.
    record_platform_event(db, actor=actor, event_type='LEAD_HARD_DELETED',
        entity_type='lead', entity_id=lead.id, company_id=lead.company_id,
        reason=reason, payload={'project_id': lead.project_id, 'version': 'p09'}, request=request)
    # PostgreSQL FK ON DELETE CASCADE physically removes dialogue/Hermes states,
    # event histories, operations, appointments, messages and context links.
    db.query(Lead).filter(Lead.id == lead.id,
        Lead.company_id == lead.company_id).delete(synchronize_session=False)
    return attachment_paths


def _clear_contact(db: Session, company_id: str, contact_id: str) -> None:
    contact = db.query(LeadContact).filter_by(id=contact_id, company_id=company_id).with_for_update().first()
    if not contact:
        return
    remaining = _contact_leads(db, company_id, contact)
    if not remaining:
        db.delete(contact)
        return
    retained = {lead.id for lead in remaining}
    contact.previous_projects = [row for row in (contact.previous_projects or [])
        if isinstance(row, dict) and row.get('lead_id') in retained]
    # A consolidated record must not retain the name/email of the deleted
    # opportunity if a different active lead is still linked to the contact.
    canonical = max(remaining, key=lambda row: (row.created_at or datetime.min, row.id))
    contact.full_name = canonical.full_name
    contact.email = canonical.email


def _delete_files(paths: list[str]) -> list[str]:
    failed = []
    for path in paths:
        try:
            storage_service.resolve_meeting_attachment(path).unlink(missing_ok=True)
        except (OSError, ValueError):
            failed.append(hashlib.sha256(path.encode()).hexdigest()[:16])
    return failed


@router.get('/admin/companies/{company_id}/leads/{lead_id}/hard-delete-preview')
def lead_preview(company_id: str, lead_id: str, db: Session = Depends(get_db),
                 actor: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return preview(db, company_id=company_id, lead_id=lead_id)


@router.delete('/admin/companies/{company_id}/leads/{lead_id}/hard-delete')
def hard_delete_lead(company_id: str, lead_id: str, payload: DeletePayload,
                     request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    _enabled()
    try:
        lead = db.query(Lead).filter_by(id=lead_id, company_id=company_id).with_for_update().first()
        if not lead:
            raise HTTPException(404, 'Lead not found within Company.')
        if lead.full_name == 'Deleted lead':
            raise HTTPException(409, 'A previously anonymized lead requires separate verified recovery of its original identity.')
        if payload.confirmation.strip().casefold() != lead.full_name.strip().casefold():
            raise HTTPException(422, 'Confirm the exact lead name.')
        contact_id = lead.contact_id
        paths = _purge_one(db, lead=lead, actor=actor, reason=payload.reason, request=request)
        if contact_id:
            _clear_contact(db, company_id, contact_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    failed = _delete_files(paths)
    return {'status': 'purged' if not failed else 'purged_with_attachment_cleanup_failures',
            'company_id': company_id, 'lead_id': lead_id,
            'attachment_cleanup_failed_hashes': failed}


@router.get('/admin/companies/{company_id}/contacts/{contact_id}/hard-delete-preview')
def contact_preview(company_id: str, contact_id: str, db: Session = Depends(get_db),
                    actor: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    contact = db.query(LeadContact).filter_by(company_id=company_id, id=contact_id).first()
    if not contact:
        raise HTTPException(404, 'Company contact not found.')
    leads = _contact_leads(db, company_id, contact)
    details = [preview(db, company_id=company_id, lead_id=lead.id) for lead in leads]
    return {'company_id': company_id, 'contact_id': contact_id,
            'opportunities': details, 'can_delete': all(row['can_delete'] for row in details)}


@router.delete('/admin/companies/{company_id}/contacts/{contact_id}/hard-delete')
def hard_delete_contact(company_id: str, contact_id: str, payload: DeletePayload,
                        request: Request, db: Session = Depends(get_db),
                        actor: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    _enabled()
    if payload.confirmation.strip() != f'DELETE CONTACT {contact_id}':
        raise HTTPException(422, detail='Confirm exactly: DELETE CONTACT <contact_id>.')
    try:
        contact = db.query(LeadContact).filter_by(company_id=company_id, id=contact_id).with_for_update().first()
        if not contact:
            raise HTTPException(404, 'Company contact not found.')
        leads = _contact_leads(db, company_id, contact)
        # Atomic all-or-nothing preflight, avoiding accidental partial erasure.
        blockers = {lead.id: _preflight(db, lead)[2] for lead in leads}
        if any(blockers.values()):
            raise HTTPException(409, detail={'code': 'P09_CONTACT_DELETE_BLOCKED', 'blockers': blockers})
        paths: list[str] = []
        for lead in leads:
            paths.extend(_purge_one(db, lead=lead, actor=actor, reason=payload.reason, request=request))
        db.query(LeadContact).filter_by(company_id=company_id, id=contact_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    failed = _delete_files(paths)
    return {'status': 'purged' if not failed else 'purged_with_attachment_cleanup_failures',
            'company_id': company_id, 'contact_id': contact_id,
            'leads_purged': len(leads), 'attachment_cleanup_failed_hashes': failed}


@router.get('/admin/companies/{company_id}/leads/{lead_id}/related-opportunities')
def related_opportunities(company_id: str, lead_id: str,
                          db: Session = Depends(get_db),
                          actor: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    lead = db.query(Lead).filter_by(company_id=company_id, id=lead_id).first()
    if not lead or lead.deleted_at:
        raise HTTPException(404, 'Active lead not found within Company.')
    from app.modules.sales_agent.p09_opportunities import company_opportunities
    return company_opportunities(db, company_id=company_id, phone=lead.phone)
