"""Exact, scoped cancellation. Reservation writes commit before retryable external effects."""
from dataclasses import replace
from datetime import datetime,timedelta
from types import SimpleNamespace
import re
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead,Meeting,MeetingStatus,CalendarConnection,FunnelStage
from app.modules.users.models import User
from .dialogue_store import Scope,check_scope
from .understanding_contract import Understanding,CancellationDirective
from .turn_configuration import digest
from .first_booking import accepted_outbound,stop_cadence,active_meetings
from .reschedule_service import resolve_original,meeting_snapshot,current_description,reservation_version
from .booking_models import SalesBookingOperation
from .reschedule_models import SalesRescheduleOperation
from .cancellation_models import SalesCancellationOperation
from .appointment_context import utc

VERSION='sales-cancellation/1.0'
OPTIONAL_REASON=' If you wish, what is your reason for cancelling?'
TERMINAL={'completed','review','simulation'}


def enabled(db,scope,project_ids):
    from .next_flow import selected
    from .active_service import selected_policy
    return all(selected(replace(scope,project_id=pid)) and selected_policy(db,replace(scope,project_id=pid)) for pid in {scope.project_id,*project_ids})


def authorize(db,scope,project_id):
    check_scope(db,scope)
    project=db.query(Project).filter_by(id=project_id,company_id=scope.company_id).populate_existing().one_or_none()
    if not project or not enabled(db,scope,[project_id]):raise PermissionError('Cancellation scope is not enabled.')
    from .sales_policy import policy_context,compliance_action_holds
    from .commercial_context import confirmed_profile_facts
    if 'appointment' in compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile),target_project_id=project_id)):
        raise PermissionError('Cancellation requires policy review.')
    # Cancelling an existing reservation never requires current catalog availability.
    return project


def directive_for(u):
    return u.cancellation or (CancellationDirective(action='request',evidence=u.visit.evidence) if u.visit and u.visit.action=='cancel' else None)


def should_handle(u,previous):
    if directive_for(u):return True
    if u.visit or u.reschedule or u.appointment_query:return False
    return bool(previous.get('cancellation_confirmation') and u.permits('appointment') or
        previous.get('cancellation_followup') and (u.courtesy or all(r.topic.value=='other' for r in u.requests)))


def enrich(u,previous,text):
    from .service import _affirmative_slot_reply
    from .turn_context import choice_index
    key=next((k for k in ['cancellation_confirmation','cancellation_meeting_offer','cancellation_followup'] if previous.get(k)),None)
    if not key:return u
    short=' '.join(re.sub('[^a-z ]',' ',text.lower()).split())
    decline=short in {'no','no thanks','no thank you','not now','no more questions','no no more questions','no that s all'}
    if key=='cancellation_meeting_offer' and choice_index(text) is not None:
        data=u.model_dump(mode='json');data.update(requests=[{'id':'choose_cancel_visit','topic':'appointment','polarity':'request','subject':None,'evidence':text}],
            all_of=['choose_cancel_visit'],alternatives=[],references=[],selected_reference_id=None,requires_clarification=False,clarification_question=None,
            cancellation={'action':'request','evidence':text,'meeting_reference':text},reschedule=None,visit=None,appointment_query=None,courtesy=None)
        return Understanding.model_validate(data)
    if previous.get('material_offer') or previous.get('release_offer'):return u
    if not decline and not (key=='cancellation_confirmation' and _affirmative_slot_reply(text)):return u
    data=u.model_dump(mode='json')
    data.update(requests=[{'id':'cancel_reply','topic':'other' if key=='cancellation_followup' else 'appointment','polarity':'request','subject':None,'evidence':text}],
        all_of=['cancel_reply'],alternatives=[],references=[],selected_reference_id=None,requires_clarification=False,clarification_question=None,
        visit=None,reschedule=None,appointment_query=None,courtesy={'kind':'farewell','evidence':text} if key=='cancellation_followup' else None,
        cancellation=None if key=='cancellation_followup' else {'action':'decline' if decline else 'confirm','evidence':text})
    return Understanding.model_validate(data)


def cleanup_target(db,row):
    receipt=db.query(SalesBookingOperation).filter_by(meeting_id=row.id).first()
    event_id=row.gcal_event_id
    if not event_id and receipt and receipt.calendar_attempts:event_id='bp'+row.id.replace('-','')
    connection=db.query(CalendarConnection).filter_by(user_id=row.assigned_sales_user_id,provider='google').first()
    return {'meeting_id':row.id,'project_id':row.project_id,'event_id':event_id,'expected_meeting_event_id':row.gcal_event_id,
        'user_id':row.assigned_sales_user_id,'connection_id':connection.id if connection else None,
        'calendar_id':connection.calendar_id if connection else None,'completed':not bool(event_id)}


def collect_cleanup(db,row):
    targets=[cleanup_target(db,row)];operations=[];seen={row.id};current=row.id
    for _ in range(10):
        op=db.query(SalesRescheduleOperation).filter_by(replacement_meeting_id=current).first()
        if not op:return targets,operations,False
        if op.original_meeting_id in seen:return targets,operations,True
        seen.add(op.original_meeting_id);operations.append(op);current=op.original_meeting_id
        old=db.get(Meeting,current)
        if not old or old.lead_id!=row.lead_id:return targets,operations,True
        saved=op.snapshot_json['cleanup']
        targets.append({'meeting_id':old.id,'project_id':old.project_id,**saved,
            'expected_meeting_event_id':saved.get('event_id'),'completed':op.calendar_status in {'completed','simulation'} or not bool(saved.get('event_id'))})
    return targets,operations,bool(db.query(SalesRescheduleOperation).filter_by(replacement_meeting_id=current).first())


def cancel(db,scope,conversation,lead,outcome,inbound,proposal):
    db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,project_id=scope.project_id).populate_existing().with_for_update().one()
    db.query(SalesBookingOperation).filter_by(meeting_id=proposal['appointment']['id']).with_for_update().all()
    row=db.query(Meeting).filter_by(id=proposal['appointment']['id'],lead_id=scope.lead_id).populate_existing().with_for_update().one_or_none()
    state=outcome.state
    if not row or row.status not in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED} or row.meeting_time<=datetime.utcnow() or reservation_version(row)!=proposal['appointment']['booking_sha256']:
        state.cancellation_proposal=None
        return 'That visit changed or is no longer eligible for this cancellation. No other reservation has been changed. Please review the current visit.',{'cancellation_context_question':True},[]
    authorize(db,scope,row.project_id)
    if lead.deleted_at or lead.is_opt_out or lead.consent_status!='granted' or lead.agent_status=='human_control':raise PermissionError('Lead permissions changed.')
    if row.assigned_sales_user_id:db.query(User).filter_by(id=row.assigned_sales_user_id).with_for_update().all()
    targets,previous,chain_limit=collect_cleanup(db,row)
    snapshot=meeting_snapshot(db,row);now=datetime.utcnow()
    from app.modules.governance.services import enqueue_notification
    with db.begin_nested():
        op=SalesCancellationOperation(company_id=scope.company_id,project_id=scope.project_id,booking_project_id=row.project_id,
            conversation_id=scope.conversation_id,lead_id=scope.lead_id,meeting_id=row.id,proposal_id=proposal['id'],
            snapshot_json={'version':VERSION,'appointment':snapshot,'cleanup':targets},
            calendar_status='review' if chain_limit else 'simulation' if row.is_demo else 'pending',
            last_error='ReplacementChainLimit' if chain_limit else None,next_attempt_at=now,notification_next_attempt_at=now,
            reason=proposal.get('reason'),reason_message_id=proposal.get('reason_message_id'))
        db.add(op);db.flush()
        row.status=MeetingStatus.CANCELLED;row.confirmation_status='cancelled_by_lead'
        booking=db.query(SalesBookingOperation).filter_by(meeting_id=row.id).first()
        if booking:booking.calendar_status='cancelled'
        for old_op in previous:old_op.calendar_status='cancelled'
        payload={'title':'Appointment cancelled','body':'Cancelled visit: '+current_description(snapshot)+'.',
            'action_url':'/app/schedule','assigned_sales_user_id':row.assigned_sales_user_id}
        if row.assigned_sales_user_id:payload['recipient_user_ids']=[row.assigned_sales_user_id]
        else:payload['recipient_roles']=['admin','assistant']
        notice=enqueue_notification(db,company_id=scope.company_id,project_id=row.project_id,event_type='appointment_cancelled',entity_type='lead',entity_id=lead.id,
            payload=payload,dedupe_key='cancellation:'+op.id)
        op.notification_outbox_id=notice.id
        db.flush()
    state.cancellation_proposal=None;state.cancellation_search={};state.cancellation_followup_id=None if op.reason else op.id
    state.booking_proposal=None;state.booking_search={};state.reschedule_proposal=None;state.reschedule_search={}
    stop_cadence(db,conversation,lead,state,'cancelled')
    if not active_meetings(db,scope):
        conversation.stage='appointment_cancelled';lead.agent_status='active'
        if lead.pipeline_stage=='S09_HANDOFF':lead.pipeline_stage='S06_NURTURE'
        if lead.funnel_stage==FunnelStage.APPOINTMENT_SET:lead.funnel_stage=FunnelStage.CONTACTED
    metadata={'cancellation_operation_id':op.id,'cancelled_meeting_id':row.id}
    if not op.reason:metadata['cancellation_followup']={'id':op.id}
    return 'Your visit has been cancelled: '+current_description(snapshot)+'. You can continue asking about other properties.'+(OPTIONAL_REASON if not op.reason else ' Your reason has been recorded.'),metadata,[
            {'type':'appointment_cancelled','meeting_id':row.id,'operation_id':op.id}]


def handle(db,scope,conversation,lead,outcome,inbound,previous):
    state=outcome.state;u=state.last_understanding;directive=directive_for(u)
    if u.cancellation and (u.reschedule or u.visit):return 'Please clarify whether you want to cancel the current visit or request a different visit. Nothing has been changed.',{'cancellation_context_question':True},[]
    if previous.get('cancellation_followup') and not (directive and directive.action=='request'):
        accepted=accepted_outbound(db,conversation,'cancellation_followup')
        op=db.query(SalesCancellationOperation).filter_by(id=state.cancellation_followup_id,company_id=scope.company_id,lead_id=scope.lead_id).first()
        if directive and directive.action=='reason' and accepted and op and previous['cancellation_followup'].get('id')==op.id and directive.reason:
            op.reason=directive.reason;op.reason_message_id=inbound.id
            state.cancellation_followup_id=None
            return 'Thank you. Your reason has been recorded. You can message whenever you have another property question.',{'cancellation_followup_closed':True},[]
        if not directive or directive.action=='decline':
            state.cancellation_followup_id=None
            return 'No reason is required. You can message whenever you have another property question.',{'cancellation_followup_closed':True},[]
    if directive and directive.action=='reason':return 'A reason is optional. No reservation has been changed by this message.',{'cancellation_followup_closed':True},[]
    if directive and directive.action=='decline':
        proposal=state.cancellation_proposal
        row=db.query(Meeting).filter_by(id=proposal['appointment']['id'],lead_id=scope.lead_id).first() if proposal else None
        kept=bool(row and row.status in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED})
        state.cancellation_search={};state.cancellation_proposal=None
        return ('I have kept your original reservation. You can continue asking questions.' if kept else 'No new cancellation has been made. You can continue asking questions.'),{'cancellation_followup_closed':True},[]
    if not u.permits('appointment') or u.requires_clarification or u.confidence<.8:return '',{},[]
    if not any(t.source_message_id==inbound.id and t.topic.value=='appointment' and t.id in outcome.plan.get('write_candidates_require_backend_authorization',[]) for t in state.tasks):return '',{},[]
    from .service import _affirmative_slot_reply
    from app.modules.governance.services import request_attribution
    assent=_affirmative_slot_reply(inbound.content)
    if directive and directive.action=='confirm':assent|=_affirmative_slot_reply(directive.evidence) and request_attribution(inbound.content)['current_text'].lstrip().startswith(directive.evidence)
    proposal=state.cancellation_proposal;prompt=accepted_outbound(db,conversation,'cancellation_confirmation')
    if assent:
        if not proposal or not prompt or prompt.metadata_json['cancellation_confirmation'].get('id')!=proposal['id']:
            return 'Please review a current cancellation summary before confirming. No reservation has been changed.',{'cancellation_context_question':True},[]
        if proposal['scope']!=scope.__dict__ or proposal['id']!=digest({k:v for k,v in proposal.items() if k!='id'}) or datetime.fromisoformat(proposal['expires_at'])<=utc(datetime.utcnow()):
            state.cancellation_proposal=None
            return 'That cancellation proposal expired or changed. Your reservation is unchanged. Please request a current summary.',{'cancellation_context_question':True},[]
        try:return cancel(db,scope,conversation,lead,outcome,inbound,proposal)
        except PermissionError:
            state.cancellation_proposal=None
            return 'The cancellation needs access or approval review. Your reservation is unchanged.',{'cancellation_context_question':True},[]
    old,rows=resolve_original(db,scope,conversation,directive,SimpleNamespace(reschedule_search=state.cancellation_search),offer_key='cancellation_meeting_offer')
    if not old:
        if not rows:return 'I could not find a future active visit eligible for cancellation. No reservation has been changed.',{'cancellation_context_question':True},[]
        return 'Which current visit would you like to cancel?\n\n'+'\n\n'.join(f'{i}. {current_description(meeting_snapshot(db,r))}' for i,r in enumerate(rows,1)),{'cancellation_meeting_offer':{'meeting_ids':[r.id for r in rows]}},[]
    try:authorize(db,scope,old.project_id)
    except PermissionError:return 'The cancellation needs access or approval review. Your reservation is unchanged.',{'cancellation_context_question':True},[]
    proposal={'version':VERSION,'scope':scope.__dict__,'appointment':meeting_snapshot(db,old),
        'reason':directive.reason if directive else None,'reason_message_id':inbound.id if directive and directive.reason else None,'expires_at':(utc(datetime.utcnow())+timedelta(minutes=30)).isoformat()}
    proposal['id']=digest(proposal);state.cancellation_proposal=proposal;state.cancellation_search={'original_meeting_id':old.id}
    state.booking_proposal=None;state.reschedule_proposal=None
    return 'Current visit: '+current_description(proposal['appointment'])+'. Your reservation will remain in place unless you confirm. Shall I cancel this exact visit?',{
        'cancellation_confirmation':{'id':proposal['id'],'expires_at':proposal['expires_at']}},[]


def validate_prepared(db,scope,metadata):
    if not metadata.get('cancellation_operation_id'):return
    op=db.query(SalesCancellationOperation).filter_by(id=metadata['cancellation_operation_id'],company_id=scope.company_id,lead_id=scope.lead_id).one()
    try:authorize(db,scope,op.booking_project_id)
    except PermissionError as exc:raise ValueError('Cancellation access changed before commit.') from exc
    row=db.get(Meeting,op.meeting_id)
    if row.status!=MeetingStatus.CANCELLED or row.confirmation_status!='cancelled_by_lead':raise ValueError('Cancellation state changed before commit.')


def advance_effect(db,operation_id):
    op=db.query(SalesCancellationOperation).filter_by(id=operation_id).populate_existing().with_for_update(skip_locked=True).first()
    if not op or op.calendar_status in TERMINAL or op.next_attempt_at>datetime.utcnow():return
    scope=Scope(op.company_id,op.project_id,op.conversation_id,op.lead_id)
    pending=[t for t in op.snapshot_json['cleanup'] if not t['completed']]
    if not enabled(db,scope,[op.booking_project_id,*[t['project_id'] for t in pending]]):return
    # Effects use saved, authenticated reservation ownership; they do not contact the lead.
    if not pending:op.calendar_status='completed';op.last_error=None;db.commit();return
    snapshot={**op.snapshot_json,'cleanup':[dict(t) for t in op.snapshot_json['cleanup']]}
    op.attempts+=1
    from app.integrations.gcalendar_client import delete_calendar_event_for_connection
    try:
        for target in snapshot['cleanup']:
            if target['completed']:continue
            row=db.query(Meeting).filter_by(id=target['meeting_id'],lead_id=op.lead_id).populate_existing().with_for_update().first()
            project=db.get(Project,target['project_id']);owner=db.query(User).filter_by(id=target['user_id'],company_id=op.company_id,deleted_at=None).first()
            connection=db.query(CalendarConnection).filter_by(id=target['connection_id'],user_id=target['user_id'],provider='google').first()
            if not row or not project or project.company_id!=op.company_id or row.project_id!=project.id or row.assigned_sales_user_id!=target['user_id'] or row.status!=MeetingStatus.CANCELLED or row.confirmation_status not in {'rescheduled','cancelled_by_lead'} or row.gcal_event_id!=target['expected_meeting_event_id'] or not owner or not connection or connection.calendar_id!=target['calendar_id']:
                op.calendar_status='review';op.last_error='CalendarBindingChanged';break
            if connection.status!='connected':
                op.attempts-=1;op.calendar_status='waiting_connection';op.next_attempt_at=datetime.utcnow()+timedelta(minutes=10);break
            delete_calendar_event_for_connection(db,connection,target['event_id'])
            row.calendar_sync_status='cancelled_removed';target['completed']=True
        else:op.calendar_status='completed';op.last_error=None
    except Exception as exc:
        op.calendar_status='review' if op.attempts>=5 else 'retry';op.last_error=type(exc).__name__
        op.next_attempt_at=datetime.utcnow()+timedelta(minutes=min(60,2**op.attempts))
    op.snapshot_json=snapshot;db.commit()


def retry_effects(db,limit=10):
    from app.core.config import settings
    from app.modules.ai_core.models import AIConfiguration
    from .runtime_policy import RuntimePolicy
    from uuid import UUID
    if not settings.SALES_DIALOGUE_RUNTIME_ENABLED or not settings.SALES_NEXT_FLOW_ENABLED:return
    ids=[v.strip() for v in settings.SALES_NEXT_FLOW_PROJECT_IDS.split(',') if v.strip()]
    try:
        if not ids or any(str(UUID(v))!=v for v in ids):return
    except ValueError:return
    config=db.query(AIConfiguration).filter_by(company_id=None).first();policy=RuntimePolicy.model_validate((config.agent_ventas or {}).get('runtime_config') or {}) if config else RuntimePolicy()
    if policy.mode!='active':return
    query=db.query(SalesCancellationOperation).filter(SalesCancellationOperation.calendar_status.in_(['pending','retry','waiting_connection']),SalesCancellationOperation.next_attempt_at<=datetime.utcnow(),SalesCancellationOperation.project_id.in_(ids),SalesCancellationOperation.booking_project_id.in_(ids))
    if policy.scope=='cohort':
        query=query.filter(SalesCancellationOperation.company_id.in_(policy.company_ids),SalesCancellationOperation.project_id.in_(policy.project_ids),SalesCancellationOperation.booking_project_id.in_(policy.project_ids))
        if policy.lead_ids:query=query.filter(SalesCancellationOperation.lead_id.in_(policy.lead_ids))
    for row in query.order_by(SalesCancellationOperation.next_attempt_at).limit(limit).all():advance_effect(db,row.id)


def process_notification(db,event):
    """A failed panel notice is observable and due for retry; the cancellation stays committed."""
    op=db.query(SalesCancellationOperation).filter_by(notification_outbox_id=event.id,company_id=event.company_id).with_for_update().first()
    if not op:
        from app.modules.governance.services import _process_notification_event
        return _process_notification_event(db,event)
    if op.notification_status in {'processed','review'} or op.notification_next_attempt_at>datetime.utcnow():return 0
    from app.modules.governance.services import _process_notification_event
    try:
        with db.begin_nested():
            created=_process_notification_event(db,event)
            if created==0:
                from app.modules.governance.models import Notification
                if not db.query(Notification).filter(Notification.dedupe_key.like(event.dedupe_key+':%')).first():raise ValueError('NoEligibleRecipient')
        op.notification_status='processed';op.notification_last_error=None;op.notification_attempts+=1
        return created
    except Exception as exc:
        op.notification_attempts+=1;op.notification_status='review' if op.notification_attempts>=5 else 'retry'
        op.notification_last_error=type(exc).__name__;op.notification_next_attempt_at=datetime.utcnow()+timedelta(minutes=min(60,2**op.notification_attempts))
        return 0


def effect_status(op):
    return {'id':op.id,'meeting_id':op.meeting_id,'cancelled':True,
        'calendar':{'status':op.calendar_status,'attempts':op.attempts,'last_error':op.last_error,'next_attempt_at':op.next_attempt_at},
        'notification':{'status':op.notification_status,'attempts':op.notification_attempts,'last_error':op.notification_last_error,'next_attempt_at':op.notification_next_attempt_at}}


def reset_effects(db,op,*,commit=True):
    """Explicit manager recovery resets only effect budgets; it never cancels or books again."""
    from app.modules.governance.models import NotificationOutbox
    event=db.query(NotificationOutbox).filter_by(id=op.notification_outbox_id).with_for_update().first()
    op=db.query(SalesCancellationOperation).filter_by(id=op.id).populate_existing().with_for_update().one()
    if op.last_error=='ReplacementChainLimit':
        from fastapi import HTTPException
        raise HTTPException(status_code=409,detail='The replacement chain requires manual Calendar reconciliation.')
    if op.calendar_status not in {'completed','simulation'}:
        op.calendar_status='pending';op.attempts=0;op.last_error=None;op.next_attempt_at=datetime.utcnow()
    if op.notification_status!='processed':
        op.notification_status='pending';op.notification_attempts=0;op.notification_last_error=None;op.notification_next_attempt_at=datetime.utcnow()
        event=db.get(NotificationOutbox,op.notification_outbox_id)
        if event:event.status='pending'
    if commit:db.commit()
    return effect_status(op)
