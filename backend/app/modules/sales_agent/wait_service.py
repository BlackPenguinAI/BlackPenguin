from .execution import now as workflow_now
from .execution import permitted
"""Explicit availability alerts. No reservation is ever created by this worker."""
from datetime import datetime,timedelta,time,date,timezone
from types import SimpleNamespace
from dataclasses import replace
from zoneinfo import ZoneInfo
import re,uuid
from app.modules.sales_crm.models import Lead,Meeting,MeetingStatus
from app.modules.projects.models import Project
from .models import SalesConversation,SalesMessage,OutboundMessage
from .wait_models import SalesWaitRequest
from .dialogue_store import Scope,check_scope,load
from .understanding_contract import Understanding,Task
from .turn_configuration import digest
from .appointment_context import utc
from .first_booking import accepted_outbound,search_slots,label,active_meetings
from .reschedule_service import authorize_target,target_context,reservation_version,meeting_snapshot
from app.modules.projects.locations import resolve_visit_location

VERSION='sales-availability-wait/1.0'
OPEN={'waiting','processing','retry','blocked_channel'}


class WaitBlocked(Exception):pass


def fixed_preferences(prefs,now):
    value=dict(prefs);today=utc(now).astimezone(ZoneInfo(value['timezone'])).date()
    first=date.fromisoformat(value['date_from']) if value.get('date_from') else today
    last=date.fromisoformat(value['date_until']) if value.get('date_until') else first+timedelta(days=13)
    if last<today or first>today+timedelta(days=90) or (last-first).days>30 or last<first:raise ValueError('Invalid alert range.')
    value.update(date_from=max(first,today).isoformat(),date_until=last.isoformat())
    return value


def interest(state):return {'property_type_id':state.selected_property_type_id,'unit_id':state.selected_unit_id}


def wait_offer(db,scope,outcome,context,prefs,*,original=None,allowed=None):
    now=workflow_now(datetime);prefs=fixed_preferences(prefs,now)
    offer={'version':VERSION,'scope':scope.__dict__,'context':context,'preferences':prefs,'interest':interest(outcome.state),
        'original':meeting_snapshot(db,original) if original else None,'allowed_user_ids':sorted(allowed) if allowed else [],
        'expires_at':(utc(now)+timedelta(minutes=30)).isoformat()}
    offer['id']=digest(offer);outcome.state.wait_context=offer
    name=context['project_name']+(' / '+context['property_type_name'] if context.get('property_type_name') else '')
    if context.get('unit_code'):name+=' / unit '+context['unit_code']
    return 'I checked up to 14 calendar days within your requested range and could not find a verified time matching those preferences. '+('Your original reservation is unchanged. ' if original else '')+f"Alert preferences: {name}; {prefs['date_from']} through {prefs['date_until']} ({prefs['timezone']}); {prefs['duration_minutes']} minutes. Would you like me to save a request to check these preferences and notify you once if a verified time becomes available?",{
        'wait_offer':offer,'booking_search_status':'no_matching_time','booking_preferences':prefs},[]


def enrich(u,previous,text):
    from .service import _affirmative_slot_reply
    if not previous.get('wait_offer') or previous.get('material_offer') or previous.get('release_offer'):return u
    short=' '.join(re.sub('[^a-z ]',' ',text.lower()).split())
    decline=short in {'no','no thanks','no thank you','not now','no more questions'}
    if not decline and not _affirmative_slot_reply(text):return u
    data=u.model_dump(mode='json');data.update(requests=[{'id':'wait_reply','topic':'appointment','subject':None,'polarity':'request','evidence':text}],all_of=['wait_reply'],alternatives=[],references=[],requires_clarification=False,clarification_question=None,visit=None,reschedule=None,cancellation=None,courtesy=None,appointment_query=None,wait={'action':'decline' if decline else 'request','evidence':text})
    return Understanding.model_validate(data)


def close(row,reason):
    row.status='closed';row.close_reason=reason;row.active_key=None;row.closed_at=workflow_now(datetime);row.lease_until=None


def close_for_lead(db,scope,reason):
    for row in db.query(SalesWaitRequest).filter_by(company_id=scope.company_id,lead_id=scope.lead_id).filter(SalesWaitRequest.status.in_(list(OPEN))).all():close(row,reason)


def search_matches(offer,state):
    search=state.reschedule_search if offer.get('original') else state.booking_search
    context=offer['context']
    if not search:return True
    for key in ['property_type_id','unit_id','location']:
        if key in search and search[key]!=context.get(key):return False
    if search.get('target_project_id') and search['target_project_id']!=context['project_id']:return False
    if offer.get('original') and search.get('original_meeting_id')!=offer['original']['id']:return False
    if offer.get('original') and sorted(search.get('allowed_user_ids',[]))!=sorted(offer.get('allowed_user_ids',[])):return False
    preferences=search.get('preferences',{}) if offer.get('original') else search
    for key in ['date_from','date_until','time_relation','time_from','time_until','timezone','duration_minutes']:
        if preferences.get(key) is not None and preferences[key]!=offer['preferences'].get(key):return False
    return True


def reconcile(db,scope,state,metadata):
    lead=db.get(Lead,scope.lead_id)
    if lead.is_opt_out or not permitted(lead):close_for_lead(db,scope,'consent_withdrawn');return
    if metadata.get('meeting_id'):close_for_lead(db,scope,'booked');return
    if metadata.get('cancellation_operation_id'):close_for_lead(db,scope,'appointment_cancelled');return
    for row in db.query(SalesWaitRequest).filter_by(company_id=scope.company_id,conversation_id=scope.conversation_id).filter(SalesWaitRequest.status.in_(list(OPEN))).all():
        if row.snapshot_json['interest']!=interest(state):close(row,'interest_changed')
        elif not search_matches(row.snapshot_json,state):close(row,'preferences_changed')


def fresh_context(db,scope,offer):
    from app.modules.ai_core.models import AIConfiguration
    db.query(AIConfiguration).filter_by(company_id=None).populate_existing().all()
    project,_=authorize_target(db,scope,offer['context']['project_id']);context=offer['context']
    fresh=target_context(db,scope,project,context['property_type_id'],context['unit_id'],resolve_visit_location(project,context['location']),context['duration_minutes'])
    if fresh!=context or not fresh['location']:raise PermissionError('Approved alert context changed.')
    return project


def original_for(db,scope,offer):
    old=offer.get('original')
    if not old:
        if active_meetings(db,scope):raise PermissionError('A visit is already active.')
        return None
    row=db.query(Meeting).filter_by(id=old['id'],lead_id=scope.lead_id).populate_existing().first()
    if not row or row.status not in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED} or row.meeting_time<=workflow_now(datetime) or reservation_version(row)!=old['booking_sha256']:raise PermissionError('Original reservation changed.')
    return row


def build_notice(scope,offer,options,*,now=None):
    from .first_booking import VERSION as BOOKING
    now=now or workflow_now(datetime);prefs=offer['preferences'];context=offer['context']
    expires=(utc(now)+timedelta(minutes=30)).isoformat()
    if offer.get('original'):
        from .reschedule_service import VERSION as RESCHEDULE
        proposal={'version':RESCHEDULE,'scope':scope.__dict__,'original':offer['original'],'target_context':context,
            'preferences':prefs,'options':options,'expires_at':expires}
        proposal['id']=digest(proposal)
        metadata={'reschedule_offer':proposal,'appointment_offer':{'version':RESCHEDULE,'slots':[v['starts_at'] for v in options],
            'options':options,'duration_minutes':prefs['duration_minutes'],'project_timezone':prefs['timezone']}}
        intro='Your original reservation is unchanged. Verified replacement options:'
    else:
        metadata={'appointment_offer':{'version':BOOKING,'slots':[v['starts_at'] for v in options],'options':options,'preferences':prefs,'context':context,
            'property_type_id':context['property_type_id'],'unit_id':context['unit_id'],'visit_location':context['location'],
            'duration_minutes':prefs['duration_minutes'],'project_timezone':prefs['timezone'],'expires_at':expires}}
        intro='Verified visit options:'
    text=intro+'\n\n'+'\n\n'.join(f'{i}. {label(o,prefs)}' for i,o in enumerate(options,1))+'\n\nAvailability can change. Which time would you like me to prepare for confirmation?'
    return text,metadata,expires


def nearby(db,scope,offer,directive):
    original=original_for(db,scope,offer);project=fresh_context(db,scope,offer)
    prefs=offer['preferences'];today=utc(workflow_now(datetime)).astimezone(ZoneInfo(prefs['timezone'])).date()
    ranges=[]
    if directive.timing:
        from .first_booking import normalize_timing
        prefs=normalize_timing(SimpleNamespace(visit=SimpleNamespace(timing=directive.timing)),directive.evidence,project,workflow_now(datetime),prefs)
        ranges=[fixed_preferences(prefs,workflow_now(datetime))]
    else:
        first=date.fromisoformat(prefs['date_from']);last=date.fromisoformat(prefs['date_until'])
        if first>today:ranges.append({**prefs,'date_from':max(today,first-timedelta(days=3)).isoformat(),'date_until':(first-timedelta(days=1)).isoformat()})
        ranges.append({**prefs,'date_from':(last+timedelta(days=1)).isoformat(),'date_until':(last+timedelta(days=3)).isoformat()})
    candidates=[]
    for values in ranges[:2]:
        try:
            for option in search_slots(db,replace(scope,project_id=project.id),values,workflow_now(datetime),excluded_meeting=original,allowed_user_ids=set(offer['allowed_user_ids']) or None):candidates.append((option,values))
        except ValueError:continue
    if not candidates:return 'I found no verified time on the nearby dates checked. Your saved preferences and any existing reservation are unchanged.',{'wait_result':True},[]
    candidates.sort(key=lambda pair:min(abs((datetime.fromisoformat(pair[0]['starts_at']).astimezone(ZoneInfo(prefs['timezone'])).date()-date.fromisoformat(offer['preferences'][k])).days) for k in ['date_from','date_until']))
    options=[]
    for option,values in candidates:
        if option['starts_at'] not in {v['starts_at'] for v in options}:options.append(option)
        if len(options)==3:break
    dates=[datetime.fromisoformat(o['starts_at']).astimezone(ZoneInfo(prefs['timezone'])).date().isoformat() for o in options]
    updated={**offer,'preferences':{**prefs,'date_from':min(dates),'date_until':max(dates)}}
    text,metadata,_=build_notice(scope,updated,options)
    return 'These nearby dates are outside or different from the original requested range. '+text,metadata,[]


def handle(db,scope,conversation,lead,outcome,inbound,previous):
    u=outcome.state.last_understanding;directive=u.wait;state=outcome.state
    if u.visit or u.reschedule or u.cancellation:return 'Please clarify whether you want an availability alert or a visit change. No reservation has been changed.',{'wait_result':True},[]
    if directive.action in {'cancel','decline'}:
        if directive.action=='cancel':close_for_lead(db,scope,'cancelled_by_lead')
        state.wait_context={}
        return ('Your availability alert request has been closed. Any existing reservation is unchanged.' if directive.action=='cancel' else 'No alert request has been added. You can continue asking about the property.'),{'wait_result':True},[]
    if not u.permits('appointment') or u.confidence<.8:return '',{},[]
    from .dialogue_tasks import restricted
    if not any(t.source_message_id==inbound.id and t.topic.value=='appointment' and not restricted(state,t) and t.id in outcome.plan.get('write_candidates_require_backend_authorization',[]) for t in state.tasks):
        return 'Your appointment preferences need confirmation before I can save or change an alert. No reservation has been changed.',{'wait_result':True},[]
    from .service import _affirmative_slot_reply
    accepted=accepted_outbound(db,conversation,'wait_offer');offer=(accepted.metadata_json or {}).get('wait_offer') if accepted else state.wait_context
    if _affirmative_slot_reply(inbound.content) and not accepted:return 'Please review a current alert question before accepting. No alert request has been added.',{'wait_result':True},[]
    if not offer or offer.get('scope')!=scope.__dict__ or offer.get('id')!=digest({k:v for k,v in offer.items() if k!='id'}) or datetime.fromisoformat(offer['expires_at'])<=utc(workflow_now(datetime)):return 'Please request current visit options and specify the property, date range and timezone before saving an alert.',{'wait_result':True},[]
    if offer['interest']!=interest(state) or not search_matches(offer,state):
        return 'Please request current visit options for your updated preferences before saving an alert. No alert request has been added.',{'wait_result':True},[]
    try:
        fresh_context(db,scope,offer);original_for(db,scope,offer)
        if directive.action=='nearby':return nearby(db,scope,offer,directive)
        fixed_preferences(offer['preferences'],workflow_now(datetime))
        if directive.timing:return 'Please request current visit options with the revised dates first, so I can save the exact preferences.',{'wait_result':True},[]
    except (PermissionError,ValueError):return 'The alert preferences need verification. No alert request has been added and your reservation is unchanged.',{'wait_result':True},[]
    # Serialize duplicate opt-ins across channels for this lead.
    db.query(Lead).filter_by(id=lead.id,company_id=scope.company_id).populate_existing().with_for_update().one()
    active_key=digest({'company_id':scope.company_id,'lead_id':scope.lead_id})
    signature=digest({k:v for k,v in offer.items() if k not in {'id','expires_at'}})
    old=db.query(SalesWaitRequest).filter_by(active_key=active_key).with_for_update().first()
    if old and old.request_key==signature and old.channel==conversation.channel and old.snapshot_json['provider']==conversation.provider and old.snapshot_json['contact_sha256']==digest(lead.phone):
        return 'Your availability alert request is already saved. It does not reserve a time. You can continue asking about the property.',{'wait_request_saved':old.id,'wait_result':True},[]
    if old:close(old,'replaced_by_new_request');db.flush()
    prefs=offer['preferences'];expires=datetime.combine(date.fromisoformat(prefs['date_until'])+timedelta(days=1),time.min,tzinfo=ZoneInfo(prefs['timezone'])).astimezone(timezone.utc).replace(tzinfo=None)
    row=SalesWaitRequest(company_id=scope.company_id,project_id=scope.project_id,target_project_id=offer['context']['project_id'],conversation_id=scope.conversation_id,lead_id=scope.lead_id,
        requested_message_id=inbound.id,active_key=active_key,request_key=signature,snapshot_json={**offer,'provider':conversation.provider,'contact_sha256':digest(lead.phone)},channel=conversation.channel,expires_at=expires,next_check_at=workflow_now(datetime))
    db.add(row);db.flush()
    return f"Your availability alert request is saved for {prefs['date_from']} through {prefs['date_until']} ({prefs['timezone']}). I will check those preferences and can send one alert if a verified time becomes available and the channel permits contact. This does not reserve a time. You can cancel the alert request at any time.",{'wait_request_saved':row.id,'wait_result':True},[{'type':'availability_wait_saved','wait_request_id':row.id}]


def validate_saved(db,scope,metadata):
    if not metadata.get('wait_request_saved'):return
    row=db.query(SalesWaitRequest).filter_by(id=metadata['wait_request_saved'],company_id=scope.company_id,lead_id=scope.lead_id).one()
    if row.status not in OPEN:raise ValueError('The alert is no longer active before commit.')
    try:fresh_context(db,scope,row.snapshot_json);original_for(db,scope,row.snapshot_json)
    except PermissionError as exc:raise ValueError('Alert approval changed before commit.') from exc


def current(db,row):
    scope=Scope(row.company_id,row.project_id,row.conversation_id,row.lead_id)
    conversation=check_scope(db,scope);lead=db.query(Lead).filter_by(id=row.lead_id).populate_existing().one()
    if row.expires_at<=workflow_now(datetime):close(row,'expired');raise WaitBlocked('Expired')
    if lead.deleted_at or lead.is_opt_out or not permitted(lead):close(row,'consent_withdrawn');raise WaitBlocked('ConsentWithdrawn')
    if conversation.channel!=row.channel or conversation.provider!=row.snapshot_json['provider'] or digest(lead.phone)!=row.snapshot_json['contact_sha256']:close(row,'contact_changed');raise WaitBlocked('ContactChanged')
    from .dialogue_models import SalesDialogueState
    scope.query(db,SalesDialogueState).populate_existing().first()
    revision,state=load(db,scope)
    if interest(state)!=row.snapshot_json['interest']:close(row,'interest_changed');raise WaitBlocked('InterestChanged')
    if not search_matches(row.snapshot_json,state):close(row,'preferences_changed');raise WaitBlocked('PreferencesChanged')
    from .dialogue_tasks import restricted
    context=row.snapshot_json['context']
    task=Task(id='wait_notification',topic='appointment',status='pending',property_id=context['property_type_id'],unit_id=context['unit_id'])
    if restricted(state,task):close(row,'appointment_permission_withdrawn');raise WaitBlocked('AppointmentPermissionWithdrawn')
    from app.modules.governance.models import HumanInterventionCase
    if conversation.is_paused or lead.agent_status=='human_control' or db.query(HumanInterventionCase).filter_by(conversation_id=conversation.id,status='open').first():raise WaitBlocked('ManualControl')
    try:
        fresh_context(db,scope,row.snapshot_json);old=original_for(db,scope,row.snapshot_json)
    except (PermissionError,ValueError) as exc:close(row,'reservation_or_approval_changed');raise WaitBlocked('ContextChanged') from exc
    inbound=db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='inbound',role='user').order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    if not inbound or state.memory.as_of_message_id!=inbound.id:raise WaitBlocked('InboundTurnPending')
    return scope,conversation,lead,revision,inbound.id,old


def contact_time(db,row,conversation):
    from .live_service import _whatsapp_customer_window_open
    if row.channel=='whatsapp' and not _whatsapp_customer_window_open(db,conversation):raise WaitBlocked('WhatsAppWindowClosed')
    if row.channel not in {'sms','whatsapp'}:raise WaitBlocked('UnsupportedChannel')
    from app.modules.governance.services import next_allowed_proactive_time
    values=[next_allowed_proactive_time(db,company_id=row.company_id,project_id=pid) for pid in {row.project_id,row.target_project_id}]
    allowed=max(values)
    if allowed>workflow_now(datetime):
        row.next_check_at=allowed
        raise WaitBlocked('OperatingWindowClosed')


def locked_request(db,identifier,*,claim=False):
    hint=db.get(SalesWaitRequest,identifier)
    if not hint:return None
    conversation=db.query(SalesConversation).filter_by(id=hint.conversation_id).populate_existing().with_for_update(skip_locked=True).first()
    if not conversation:return None
    db.query(Lead).filter_by(id=hint.lead_id).populate_existing().with_for_update().first()
    query=db.query(SalesWaitRequest).filter_by(id=identifier).populate_existing().with_for_update(skip_locked=True)
    row=query.first()
    if not row or row.status not in OPEN:return None
    if claim and (row.next_check_at>workflow_now(datetime) and row.expires_at>workflow_now(datetime) or row.status=='processing' and row.lease_until and row.lease_until>workflow_now(datetime)):return None
    return row


def authorize_part(db,conversation,lead,metadata,content,*,before_provider=False):
    """Recheck every part immediately before the provider, including queued retries."""
    identifier=metadata.get('wait_request_id');row=locked_request(db,identifier)
    if not row or row.status!='processing' or row.claim_token!=metadata.get('wait_claim_token'):raise WaitBlocked('AlertNoLongerActive')
    if row.company_id!=conversation.company_id or row.conversation_id!=conversation.id or row.lead_id!=lead.id:raise PermissionError('Alert dispatch scope changed.')
    scope,_,_,revision,inbound_id,old=current(db,row);contact_time(db,row,conversation)
    if revision!=row.anchor_revision or inbound_id!=row.anchor_inbound_id:raise WaitBlocked('ConcurrentInboundTurn')
    payload=row.notice_json
    if not payload or metadata.get('wait_notice_sha256')!=digest(payload) or datetime.fromisoformat(payload['expires_at'])<=utc(workflow_now(datetime)):close(row,'notice_expired');raise WaitBlocked('NoticeExpired')
    from .response_policy import render_channel_text,split_channel_text
    expected=split_channel_text(render_channel_text(payload['text'],row.channel),row.channel)
    group=metadata.get('delivery_group',{});index=group.get('part',1)-1
    if group.get('total',1)!=len(expected) or not 0<=index<len(expected) or content!=expected[index]:raise PermissionError('Alert content changed during dispatch.')
    if before_provider:
        row.lease_until=workflow_now(datetime)+timedelta(minutes=10)
        from app.modules.sales_crm.scheduling import eligible_users_for_slot
        for option in payload['options']:
            starts=datetime.fromisoformat(option['starts_at']).astimezone(timezone.utc).replace(tzinfo=None)
            if starts<=workflow_now(datetime) or option['sales_user_id'] not in eligible_users_for_slot(db,project_id=row.target_project_id,starts_at=starts,duration_minutes=row.snapshot_json['preferences']['duration_minutes'],excluded_meeting=old,allowed_sales_user_ids={option['sales_user_id']}):
                close(row,'offered_time_changed');raise WaitBlocked('OfferedTimeChanged')


async def process_one(db,identifier):
    row=locked_request(db,identifier,claim=True)
    if not row:return
    token=str(uuid.uuid4())
    try:
        scope,conversation,lead,revision,inbound_id,old=current(db,row);contact_time(db,row,conversation)
        row.anchor_revision=revision;row.anchor_inbound_id=inbound_id
        row.status='processing';row.claim_token=token;row.lease_until=workflow_now(datetime)+timedelta(minutes=10);db.commit()
        if not row.notice_json:
            preferences=row.snapshot_json['preferences']
            today=utc(workflow_now(datetime)).astimezone(ZoneInfo(preferences['timezone'])).date()
            first=max(today,date.fromisoformat(preferences['date_from']))
            scan=max(first,date.fromisoformat(row.scan_date)) if row.scan_date else first
            last=date.fromisoformat(preferences['date_until'])
            if scan>last or scan>today+timedelta(days=90):scan=first
            until=min(last,scan+timedelta(days=13),today+timedelta(days=90))
            check_preferences={**preferences,'date_from':scan.isoformat(),'date_until':until.isoformat()}
            options=search_slots(db,replace(scope,project_id=row.target_project_id),check_preferences,workflow_now(datetime),excluded_meeting=old,allowed_user_ids=set(row.snapshot_json['allowed_user_ids']) or None)
            next_scan=until+timedelta(days=1) if until<last else first
            row=db.query(SalesWaitRequest).filter_by(id=identifier).populate_existing().with_for_update().one()
            if row.status!='processing' or row.claim_token!=token:db.rollback();return
            if old:
                original=row.snapshot_json['original'];context=row.snapshot_json['context']
                options=[o for o in options if not (o['starts_at']==original['starts_at'] and o['sales_user_id']==original['sales_user_id'] and context['project_id']==original['project_id'] and context['property_type_id']==original['property_type_id'] and context['unit_id']==original['unit_id'] and context['location']==original['location'] and context['duration_minutes']==original['duration_minutes'])]
            if not options:
                row.scan_date=next_scan.isoformat();row.status='waiting';row.next_check_at=workflow_now(datetime)+timedelta(minutes=15);row.lease_until=None;row.last_error=None;db.commit();return
            text,metadata,expires=build_notice(scope,row.snapshot_json,options)
            from .language_policy import detect,scoped_names
            from .commercial_context import build_commercial_context
            project=db.get(Project,row.target_project_id)
            commercial=build_commercial_context(db,project=project,company_id=row.company_id,lead_id=row.lead_id,channel=row.channel)
            if detect(text,names=scoped_names(project,lead,commercial),output=True).needs_reentry:raise WaitBlocked('OutputLanguageReview')
            row.notice_json={'text':text,'metadata':metadata,'options':options,'expires_at':expires};db.commit()
        if datetime.fromisoformat(row.notice_json['expires_at'])<=utc(workflow_now(datetime)):close(row,'notice_expired');db.commit();return
        from . import live_service
        row.attempts+=1;db.commit()
        metadata={**row.notice_json['metadata'],'wait_request_id':row.id,'wait_notice_sha256':digest(row.notice_json),'wait_claim_token':token,'engine':VERSION,'event_kind':'availability_wait_alert'}
        message=await live_service._dispatch(db,conversation=conversation,lead=lead,content=row.notice_json['text'],role='assistant',agent_run_id=None,
            metadata=metadata,idempotency_key='availability-wait:'+row.id)
        from .reference_resolution import accepted
        group=message.metadata_json.get('delivery_group',{})
        parts=db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound').all()
        matched=[p for p in parts if (p.metadata_json or {}).get('delivery_group',{}).get('key')==group.get('key')]
        complete={p.metadata_json['delivery_group']['part'] for p in matched if accepted(p)}==set(range(1,group.get('total',1)+1))
        db.refresh(row)
        if row.status not in OPEN or row.claim_token!=token:db.commit();return
        if complete:
            row.status='notified';row.notified_message_id=message.id;row.active_key=None;row.closed_at=workflow_now(datetime);row.lease_until=None;row.last_error=None
        elif all(p.status=='failed' or accepted(p) for p in matched) and any(p.status=='failed' for p in matched):
            row.status='review' if row.attempts>=3 else 'retry';row.last_error='ProviderRejected';row.next_check_at=workflow_now(datetime)+timedelta(minutes=2**row.attempts);row.lease_until=None
            if row.status=='review':row.active_key=None
        else:row.status='review';row.active_key=None;row.lease_until=None;row.last_error='ProviderOutcomeUnknown'
        db.commit()
    except WaitBlocked as exc:
        if row.status in OPEN and row.claim_token in {None,token}:
            row.status='blocked_channel';row.last_error=str(exc);row.lease_until=None
            row.next_check_at=max(row.next_check_at,workflow_now(datetime)+timedelta(minutes=15))
        db.commit()
    except Exception as exc:
        # Network timeouts can be ambiguous. Do not automatically send another alert.
        db.rollback();row=db.get(SalesWaitRequest,identifier)
        if row and row.status in OPEN and row.claim_token in {None,token}:
            row.status='review';row.active_key=None;row.lease_until=None;row.last_error=type(exc).__name__;db.commit()


async def process_due(limit=10):
    from app.db.postgres import SessionLocal
    db=SessionLocal()
    try:
        from sqlalchemy import or_
        now=workflow_now(datetime)
        query=db.query(SalesWaitRequest).filter(SalesWaitRequest.status.in_(list(OPEN)),
            or_(SalesWaitRequest.next_check_at<=now,SalesWaitRequest.expires_at<=now),or_(SalesWaitRequest.lease_until.is_(None),SalesWaitRequest.lease_until<=now))
        values=[r.id for r in query.order_by(SalesWaitRequest.next_check_at).limit(max(1,min(limit,10))).all()]
        db.commit()
        for identifier in values:await process_one(db,identifier)
    finally:db.close()
