"""Verified requests for human contact, separate from manual chat takeover.

Use the existing scoped review queue for durability; do not promise delivery,
assignment or a callback deadline. All mutations belong to the prepared turn.
"""
import re
from datetime import datetime
from . import continuity
from .continuity_policy import evidenced_pause_reason
from .conversation_scope import scoped_messages_query
from .models import SalesMessage,SalesFollowUpJob
from app.modules.governance.models import HumanInterventionCase

VERSION='sales-human-contact/1.0'
REASON='HUMAN_CONTACT_REQUEST'
FIRST='I can help with questions about the property, pricing and visits. What would you like to ask?'
RECORDED="I've saved your request to speak with the Sales team. Is there another property question I can help with? If not, thank you for your interest and have a good day."


def _state(conversation):
    value=continuity.state(conversation)
    prior=value.get('human_contact') or {}
    return prior if prior.get('epoch')==value['epoch'] else {}


def cases(db,scope):
    return db.query(HumanInterventionCase).filter_by(company_id=scope.company_id,
        project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=scope.lead_id,reason=REASON)


def withdrawal(text):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    return bool(re.search(r"\b(?:I (?:do not|don't|don’t|no longer) (?:want|need)(?: to (?:speak|talk))?(?: with| to)? (?:a |an )?(?:human|person|sales representative)|cancel my (?:human contact|request to (?:speak|talk) (?:with|to) (?:a |an )?(?:human|person)))\b",own,re.I))


def stage(db,scope,conversation,text,previous_meta):
    if withdrawal(text) and (_state(conversation).get('stage') in {'asked','recorded'} or cases(db,scope).filter_by(status='open').first()):return 'withdraw'
    if previous_meta.get('control_confirmation')=='human':
        from .service import _affirmative_slot_reply
        if _affirmative_slot_reply(text):return 'record'
    if evidenced_pause_reason(text)!='HUMAN_REQUESTED':return None
    prior=_state(conversation)
    if prior.get('stage')=='recorded' and cases(db,scope).filter_by(id=prior.get('case_id'),status='open').first():return 'record'
    prompted=scoped_messages_query(db,conversation).filter_by(direction='outbound',role='assistant').all()
    if prior.get('stage')=='asked' and any(continuity.accepted(m) and
        (m.metadata_json or {}).get('human_contact_prompt_inbound_id')==prior.get('inbound_id') for m in prompted):return 'record'
    return 'ask'


def mixed_question(text):
    # Pure requests need no model. Independent property questions still use the
    # normal interpreter/tools; a failed interpretation cannot erase the request.
    return bool(re.search(r'\b(?:what|how|which|where|when|show|send|explain)\b.{0,100}\b(?:price|cost|bedroom|bathroom|property|properties|photos|brochure|financing|location|amenities|available|availability)\b',text,re.I))


def apply(db,scope,conversation,lead,outcome,inbound,step):
    from app.modules.governance.services import record_platform_event
    from .dialogue_store import check_scope
    checked=check_scope(db,scope)
    if checked.id!=conversation.id or checked.lead_id!=lead.id:raise PermissionError('Human contact request outside opportunity.')
    value=continuity.state(conversation)
    prior=_state(conversation)
    meta={'version':VERSION,'human_contact_stage':step}
    if step=='withdraw':
        for row in cases(db,scope).filter_by(status='open').all():
            row.status='cancelled';row.resolved_at=datetime.utcnow()
        value['human_contact']={'epoch':value['epoch'],'stage':'withdrawn','inbound_id':inbound.id}
        message='Your request for human contact has been cancelled. Is there another property question I can help with?'
    elif step=='ask':
        value['human_contact']={'epoch':value['epoch'],'stage':'asked','inbound_id':inbound.id}
        meta['human_contact_prompt_inbound_id']=inbound.id
        message=FIRST
        if any(r.status in {'success','partial'} and any(t.id==r.operation_id and t.topic.value not in {'human','other'} for t in outcome.state.tasks) for r in outcome.results):
            message='I can help with property questions here. Is there another question I can help with?'
    else:
        row=cases(db,scope).filter_by(status='open').first()
        if row is None:
            # A resolved request releases the unique open-request key, retaining
            # its historical row. Never reuse a case from another opportunity.
            key='human-contact:'+scope.lead_id+':open'
            for old in cases(db,scope).filter_by(dedupe_key=key).all():old.dedupe_key=key+':closed:'+old.id
            db.flush()
            row=HumanInterventionCase(company_id=scope.company_id,project_id=scope.project_id,
                conversation_id=scope.conversation_id,lead_id=scope.lead_id,reason=REASON,
                evidence=inbound.content,dedupe_key=key,status='open')
            db.add(row);db.flush()
        value['human_contact']={'epoch':value['epoch'],'stage':'recorded','inbound_id':inbound.id,'case_id':row.id}
        meta.update(human_contact_request_id=row.id,human_contact_stage='recorded')
        from .first_booking import stop_cadence
        stop_cadence(db,conversation,lead,outcome.state,'declined')
        # Cancel marketing/inactivity work, not meetings or appointment reminders.
        for job in db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id).filter(SalesFollowUpJob.status.in_(['pending','processing'])).all():
            if job.kind=='inactivity' or job.reason.endswith('_cadence'):job.status='cancelled'
        message=RECORDED
        if re.search(r'(?:^|[.!?;])\s*(?:no (?:other|more|further) questions|nothing else)\b',inbound.content,re.I):
            message="I've saved your request to speak with the Sales team. Thank you for your interest and have a good day."
    conversation.continuity_json=value
    for task in outcome.state.tasks:
        if task.source_message_id==inbound.id and task.topic.value=='human':task.status='completed'
    record_platform_event(db,actor=None,company_id=scope.company_id,event_type='human_contact_'+step,
        entity_type='sales_conversation',entity_id=scope.conversation_id,
        payload={'lead_id':scope.lead_id,'project_id':scope.project_id,'message_id':inbound.id,**meta})
    db.flush()
    return message,meta
