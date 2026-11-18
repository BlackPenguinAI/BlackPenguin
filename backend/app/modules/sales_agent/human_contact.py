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
REASON='HUMAN_REQUESTED'
FIRST=('I can help with property details, prices, materials and visits here. '
       'Do you still want to request a human review and pause automated replies? '
       'Reply Yes to confirm, or ask me another property question.')
RECORDED=('Your human-review request has been recorded. Automated replies are paused '
          'while an administrator reviews this conversation.')


def _state(conversation):
    value=continuity.state(conversation)
    prior=value.get('human_contact') or {}
    return prior if prior.get('epoch')==value['epoch'] else {}


def cases(db,scope):
    return db.query(HumanInterventionCase).filter_by(company_id=scope.company_id,
        project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=scope.lead_id).filter(
            HumanInterventionCase.reason.in_([REASON, 'HUMAN_CONTACT_REQUEST']))


def withdrawal(text):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    return bool(re.search(r"\b(?:I (?:do not|don't|don’t|no longer) (?:want|need)(?: to (?:speak|talk))?(?: with| to)? (?:a |an )?(?:human|person|sales representative)|cancel my (?:human contact|request to (?:speak|talk) (?:with|to) (?:a |an )?(?:human|person)))\b",own,re.I))


def stage(db,scope,conversation,text,previous_meta):
    prior=_state(conversation)
    if withdrawal(text) and (prior.get('stage') in {'asked','recorded'} or cases(db,scope).filter_by(status='open').first()):return 'withdraw'
    # "Yes" may confirm only the explicit, delivered human-review question;
    # an LLM-generated transfer suggestion is NOT such an authorization.
    if (prior.get('stage')=='asked' and prior.get('inbound_id')
            and previous_meta.get('human_contact_prompt_inbound_id')==prior['inbound_id']):
        from .first_booking import accepted_outbound
        from .service import _affirmative_slot_reply
        if accepted_outbound(db,conversation,'human_contact_prompt_inbound_id') and _affirmative_slot_reply(text):
            return 'record'
    if evidenced_pause_reason(text)!='HUMAN_REQUESTED':return None
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
        # Reuse the established protected intervention path: it atomically
        # opens the scoped case, pauses AI, cancels pending cadence and enqueues
        # the company's administrator notification. No separate handoff mode.
        from app.modules.governance.services import create_intervention_case
        row=create_intervention_case(db,conversation=conversation,lead=lead,
                                     reason='HUMAN_REQUESTED',evidence=inbound.content)
        value['human_contact']={'epoch':value['epoch'],'stage':'recorded','inbound_id':inbound.id,'case_id':row.id}
        meta.update(human_contact_request_id=row.id,human_contact_stage='recorded',
                    human_intervention_case_id=row.id,control_outcome='handoff',reason='HUMAN_REQUESTED')
        from .first_booking import stop_cadence
        stop_cadence(db,conversation,lead,outcome.state,'declined')
        # Cancel marketing/inactivity work, not meetings or appointment reminders.
        for job in db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id).filter(SalesFollowUpJob.status.in_(['pending','processing'])).all():
            if job.kind=='inactivity' or job.reason.endswith('_cadence'):job.status='cancelled'
        message=RECORDED
        if re.search(r'(?:^|[.!?;])\s*(?:no (?:other|more|further) questions|nothing else)\b',inbound.content,re.I):
            message=RECORDED
    conversation.continuity_json=value
    for task in outcome.state.tasks:
        if task.source_message_id==inbound.id and task.topic.value=='human':task.status='completed'
    record_platform_event(db,actor=None,company_id=scope.company_id,event_type='human_contact_'+step,
        entity_type='sales_conversation',entity_id=scope.conversation_id,
        payload={'lead_id':scope.lead_id,'project_id':scope.project_id,'message_id':inbound.id,**meta})
    db.flush()
    return message,meta
