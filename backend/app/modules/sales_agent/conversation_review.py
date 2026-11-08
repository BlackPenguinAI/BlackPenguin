"""Scoped incident visibility and durable administrator review, without replay."""
from datetime import datetime
from fastapi import HTTPException

from app.modules.governance.models import HumanInterventionCase, PlatformAuditEvent
from app.modules.governance.services import record_platform_event
from app.modules.users.models import User, TENANT_MANAGER_ROLES
from .models import AgentRun, SalesMessage
from .conversation_scope import scoped_messages_query
from .continuity_policy import trigger_fingerprint


def review_snapshot(db, conversation):
    cases = db.query(HumanInterventionCase).filter_by(
        conversation_id=conversation.id, company_id=conversation.company_id,
        project_id=conversation.project_id, lead_id=conversation.lead_id,
    ).order_by(HumanInterventionCase.created_at.desc(),HumanInterventionCase.id.desc()).limit(10).all()
    events = db.query(PlatformAuditEvent).filter_by(
        company_id=conversation.company_id,entity_type='sales_conversation',entity_id=conversation.id,
    ).filter(PlatformAuditEvent.event_type.in_(['conversation_resumed','conversation_false_positive'])).order_by(
        PlatformAuditEvent.created_at.desc()).limit(10).all()
    resolutions = {}
    for event in events:
        actor = db.get(User,event.actor_user_id) if event.actor_user_id else None
        reviewer_name = (' '.join(filter(None,[actor.first_name,actor.last_name])) or actor.email) if actor else 'Administrator'
        for identifier in (event.payload_json or {}).get('case_ids',[]):
            resolutions.setdefault(identifier,{'note':event.reason,'actor_user_id':event.actor_user_id,'reviewer_name':reviewer_name,'at':event.created_at})
    run = db.query(AgentRun).filter_by(conversation_id=conversation.id).order_by(AgentRun.started_at.desc(),AgentRun.id.desc()).first()
    # Only expose the active opportunity's run, never a prior lead on a reused thread.
    snapshot = (run.input_snapshot or {}) if run else {}
    message = scoped_messages_query(db,conversation).filter(SalesMessage.id == snapshot.get('message_id')).first() if snapshot.get('message_id') else None
    active_run = run if run and message else None
    output = (active_run.output_snapshot or {}) if active_run else {}
    issue = None
    if active_run and active_run.error_code:
        issue = {'reason':active_run.error_code,'conversation_paused':conversation.is_paused,
                 'message':'The last response could not be processed. The AI conversation remains available for a new message.'}
    notice = (output.get('metadata') or {}).get('review_notice')
    return {
        'intervention_cases':[{'id':c.id,'reason':c.reason,'evidence':c.evidence,'confidence':c.confidence,
            'status':c.status,'created_at':c.created_at,'resolved_at':c.resolved_at,
            'resolved_by_user_id':c.resolved_by_user_id,'resolution':resolutions.get(c.id)} for c in cases],
        'processing_issue':issue,'review_notice':notice,
    }


def resolve_cases(db, conversation, lead, *, actor_user_id=None, case_id=None, false_positive=False, note=None):
    actor = db.get(User,actor_user_id) if actor_user_id else None
    if false_positive and (not actor or actor.company_id != conversation.company_id or actor.role not in TENANT_MANAGER_ROLES):
        raise HTTPException(status_code=403,detail='Only a Company administrator or assistant can review false positives.')
    if false_positive and (not case_id or not (note or '').strip()):
        raise HTTPException(status_code=422,detail='Select the open incident and explain why it is a false positive.')
    cases = db.query(HumanInterventionCase).filter_by(
        conversation_id=conversation.id,company_id=conversation.company_id,
        project_id=conversation.project_id,lead_id=conversation.lead_id,status='open',
    ).all()
    if case_id and (len(cases) != 1 or cases[0].id != case_id):
        raise HTTPException(status_code=409,detail='The open incident changed. Refresh and review its current reason.')
    if false_positive:
        meta = dict(lead.meta_form_data or {})
        dismissed = list(meta.get('dismissed_pause_triggers') or [])
        fingerprint = trigger_fingerprint(conversation.id,cases[0].reason,cases[0].evidence)
        meta['dismissed_pause_triggers'] = list(dict.fromkeys([*dismissed,fingerprint]))[-100:]
        lead.meta_form_data = meta
    for case in cases:
        case.status = 'false_positive' if false_positive else 'resolved'
        case.resolved_at = datetime.utcnow()
        case.resolved_by_user_id = actor_user_id
        # Preserve the historic case and release the unique open-reason key.
        case.dedupe_key = f'{case.reason}:closed:{case.id}'
    record_platform_event(db,actor=actor,company_id=conversation.company_id,
        event_type='conversation_false_positive' if false_positive else 'conversation_resumed',
        entity_type='sales_conversation',entity_id=conversation.id,reason=(note or '').strip() or 'Staff resumed the AI conversation',
        payload={'case_ids':[c.id for c in cases],'lead_id':lead.id,'project_id':conversation.project_id,
                 'previous_pause_reason':conversation.pause_reason,'false_positive':false_positive,'replayed_messages':0})
