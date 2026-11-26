"""HEI-03B.4: scoped live appointment changes via native reservation services.

Only a single, future, same-project real visit can be changed. The model
proposes; the buyer sees a backend-rendered recap and confirms in a later
turn. Existing Calendar/notification outboxes own external effects.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo
import re

from .production_tools import ProductionToolError, _hash, _utc
from .engine_selection import HERMES, require_selectable

CHANGE_VERSION = 'hermes-live-change/1'
TOOLS = {'cancel':'cancel_onsite_visit', 'reschedule':'reschedule_onsite_visit'}
DIRECT_CANCEL = re.compile(r"\s*(?:please\s+|i\s+(?:want|would like)\s+to\s+)?cancel\s+(?:my|the|this)\s+(?:visit|appointment|booking)[.!]?\s*", re.I)
DIRECT_RESCHEDULE = re.compile(r"\s*(?:please\s+|i\s+(?:want|would like)\s+to\s+)?(?:reschedule|change)\s+(?:my|the|this)\s+(?:visit|appointment|booking)\s+(?:to|for)\s+(?P<when>[\w\s,:/\-]+)[.!]?\s*", re.I)
EXACT_WHEN = re.compile(r"\s*(?:on\s+)?(?:\d{4}-\d{2}-\d{2}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?)\s+(?:at\s+)?(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:am|pm))?\s*", re.I)
ASSENT = re.compile(r"\s*(?:yes(?:,?\s+please)?|(?:yes,?\s+)?i\s+confirm(?:\s+(?:the\s+)?(?:cancellation|rescheduling|change))?|confirm\s+(?:the\s+)?(?:cancellation|rescheduling|change))[.!]?\s*", re.I)


def direct_replacement(text):
    match=DIRECT_RESCHEDULE.fullmatch(text)
    return bool(match and EXACT_WHEN.fullmatch(match['when']))


def _error(code, text):
    return {'error_code':code,'error':text,'next_action':'Ask for one explicit clarification; never claim the visit changed.'}


def active_visits(db, scope, *, now):
    from app.modules.sales_crm.models import Meeting, MeetingStatus
    from app.modules.sales_agent.reschedule_service import meeting_snapshot
    rows=db.query(Meeting).filter_by(lead_id=scope.lead_id,project_id=scope.project_id,is_demo=False).filter(
        Meeting.status.in_([MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED]),
        Meeting.meeting_time>_utc(now).replace(tzinfo=None)).order_by(Meeting.meeting_time,Meeting.id).all()
    # No cross-project IDs or calendar credentials reach the model.
    return [meeting_snapshot(db,row) for row in rows]


def _property_ref(old):
    return old.get('unit_code') or old.get('unit_id') or old.get('property_type_id')


def _old_label(old):
    local=datetime.fromisoformat(old['starts_at']).astimezone(ZoneInfo(old['timezone']))
    name=old.get('unit_code') or old.get('property_type_name') or old['project_name']
    return f"{name} on {local:%Y-%m-%d} at {local:%H:%M} ({old['timezone']}), {old['location']['address']}"


def change_recap(request):
    old=_old_label(request['original'])
    from app.modules.sales_agent.response_policy import render_channel_text
    if request['kind']=='cancel':
        return render_channel_text(f'Current visit: {old}. Please confirm: cancel this exact visit?')
    return render_channel_text(f'Current visit: {old}.\n\nProposed replacement: {request["property_name"]} on '
            f'{request["date"]} at {request["start_time"]} ({request["timezone"]}), {request["visit_address"]}. '
            'Your original visit stays reserved until the replacement is secured. Confirm this change?')


def recap_matches(text, request):
    if request.get('live_change_version')!=CHANGE_VERSION or request.get('kind') not in TOOLS:
        return False
    try:return text==change_recap(request)
    except (ValueError,KeyError,TypeError):return False


def draft_change(port, kind, args):
    """Read-only tool draft: scoped appointment, explicit intent and later assent."""
    from .bp_operational_port import _fresh
    from .contextual_choices import explicit_date, explicit_time
    scope=port.snapshot.scope; now=port.now
    visits=active_visits(port.db,scope,now=now)
    mid=args.get('meeting_id' if kind=='cancel' else 'original_meeting_id')
    if len(visits)!=1 or visits[0]['id']!=mid:
        return _error('EXACT_VISIT_REQUIRED','Only one unambiguous active visit in this project may be changed.')
    old=visits[0];prior=port.state.get('confirmation_request') or {}
    if (prior.get('live_change_version')==CHANGE_VERSION and prior.get('kind')==kind
            and prior.get('status')=='awaiting_confirmation'):
        if (not ASSENT.fullmatch(port.message) or not _fresh(prior,now) or not prior.get('recap_message_id')
                or prior.get('original')!=old or prior.get('selected_inbound_message_id')==port.inbound_id):
            return _error('CHANGE_CONFIRMATION_REQUIRED','Confirm the current exact recap; the original visit is unchanged.')
        if kind=='reschedule' and any(args.get(a)!=prior.get(b) for a,b in [('proposal_id','proposal_id'),('unit_id','unit_id'),('date_str','date'),('start_time','start_time')]):
            return _error('CHANGE_DETAILS_MISMATCH','The replacement differs from the recap.')
        port.state['confirmation_request']={**prior,'status':'execution_requested','confirmed_inbound_message_id':port.inbound_id}
        return {'ok':True,'status':'pending_backend_commit','changed':False}
    if kind=='cancel' and not DIRECT_CANCEL.fullmatch(port.message):
        return _error('CHANGE_INTENT_REQUIRED','Please explicitly request cancellation of your visit.')
    request={'id':str(uuid4()),'kind':kind,'status':'recap_required','live_change_version':CHANGE_VERSION,
             'original':old,'meeting_id':mid,'selected_inbound_message_id':port.inbound_id,
             'expires_at':(now+timedelta(minutes=10)).isoformat()}
    if kind=='reschedule':
        if not direct_replacement(port.message):
            return _error('CHANGE_INTENT_REQUIRED','Please explicitly request a new date and time for your visit.')
        offer=port.state.get('last_slot_search') or {}
        exact=[o for o in offer.get('options',[]) if o.get('date')==args.get('date_str') and o.get('start_time')==args.get('start_time')]
        ref=_property_ref(old)
        # A replacement changes time only, never property/project/location.
        if (not ref or not _fresh(offer,now) or not offer.get('source_reply_message_id') or len(exact)!=1
                or offer.get('project_id')!=scope.project_id or offer.get('unit_id')!=ref
                or args.get('unit_id')!=ref or args.get('proposal_id')!=offer.get('proposal_id')
                or offer.get('timezone')!=old['timezone'] or old['duration_minutes']!=60
                or explicit_time(port.message)!=exact[0]['start_time']
                or explicit_date(port.message,anchor_year=int(exact[0]['date'][:4]))!=exact[0]['date']):
            return _error('EXACT_REPLACEMENT_REQUIRED','Choose an exact offered date and hour for the same property.')
        if not old['location'].get('address') or old['location']['address']=='Address not recorded':
            return _error('LOCATION_REQUIRED','The original visit location requires staff review.')
        request.update(exact[0],unit_id=ref,proposal_id=offer['proposal_id'],timezone=offer['timezone'],
            property_name=old.get('unit_code') or old.get('property_type_name') or old['project_name'],
            visit_address=old['location']['address'],offer_message_id=offer['source_reply_message_id'])
    port.state['confirmation_request']=request
    return {'ok':True,'status':'recap_required','recap':change_recap(request),'changed':False}


def authorize_native_change(db, scope, project_id):
    """Explicit Hermes authorization, not a LangGraph cohort override."""
    from .bp_context import require_scoped_entities
    from .native_effects import _assert_business_policy
    from app.modules.onboarding_versions import require_capability
    require_selectable(HERMES)
    _,project,lead,conversation=require_scoped_entities(db,scope)
    if (project_id!=scope.project_id or conversation.channel not in {'sms','whatsapp'} or project.is_demo
            or lead.is_demo or lead.deleted_at or lead.is_opt_out or lead.consent_status!='granted'
            or lead.agent_status=='human_control' or conversation.is_paused):
        raise ProductionToolError('Appointment change scope or consent changed.')
    require_capability(project.profile,'appointments')
    _assert_business_policy(db,scope,'book')
    return project


def _verify_evidence(db,scope,conversation,inbound,request,state,now):
    from .bp_operational_port import _fresh
    from .production_tools import _verify_provider_receipt
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    if (request.get('live_change_version')!=CHANGE_VERSION or request.get('kind') not in TOOLS
            or request.get('status')!='execution_requested' or not _fresh(request,now)
            or request.get('confirmed_inbound_message_id')!=inbound.id or not ASSENT.fullmatch(inbound.content)):
        raise ProductionToolError('A later explicit confirmation of a fresh change is required.')
    q=scoped_messages_query(db,conversation)
    recap=q.filter_by(id=request.get('recap_message_id')).one_or_none()
    _verify_provider_receipt(db,recap,scope,conversation.channel)
    selection=q.filter_by(id=request.get('selected_inbound_message_id'),direction='inbound',role='user').one_or_none()
    latest=q.filter(SalesMessage.created_at<=inbound.created_at,SalesMessage.id!=inbound.id).order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    if (not selection or not selection.provider_message_id or (selection.metadata_json or {}).get('lead_id')!=scope.lead_id
            or not latest or latest.id!=recap.id or not recap_matches(recap.content,request)
            or not (selection.created_at,selection.id)<(recap.created_at,recap.id)<(inbound.created_at,inbound.id)):
        raise ProductionToolError('The exact recap was not accepted immediately before confirmation.')
    if request['kind']=='cancel':
        if not DIRECT_CANCEL.fullmatch(selection.content):raise ProductionToolError('Original cancellation request is missing.')
    else:
        from .contextual_choices import explicit_date,explicit_time,_date_label,_time_label
        stored=state.get('last_slot_search') or {}
        if (not _fresh(stored,now) or stored.get('proposal_id')!=request.get('proposal_id')
                or stored.get('source_reply_message_id')!=request.get('offer_message_id')
                or stored.get('project_id')!=scope.project_id or stored.get('unit_id')!=request.get('unit_id')
                or stored.get('timezone')!=request.get('timezone') or not any(
                    all(o.get(k)==request.get(k) for k in ('date','start_time','starts_at_utc')) for o in stored.get('options',[]))):
            raise ProductionToolError('The persisted replacement offer expired or changed.')
        offer=q.filter_by(id=request.get('offer_message_id')).one_or_none()
        _verify_provider_receipt(db,offer,scope,conversation.channel)
        text=offer.content.casefold()
        if (not direct_replacement(selection.content) or explicit_time(selection.content)!=request['start_time']
                or explicit_date(selection.content,anchor_year=int(request['date'][:4]))!=request['date']
                or not (offer.created_at,offer.id)<(selection.created_at,selection.id)
                or not any(x.casefold() in text for x in [request['unit_id'],request['property_name']])
                or not any(x.casefold() in text for x in [request['date'],_date_label(request['date'])])
                or not any(x.casefold() in text for x in [request['start_time'],_time_label(request['start_time'])])):
            raise ProductionToolError('Replacement slot was not offered and selected explicitly.')


def _native_state():
    # Native functions use a short-lived state object to clear their proposal
    # and stop cadence; never persist this object in the LangGraph store.
    return SimpleNamespace(state=SimpleNamespace())


def _execute_native(db,scope,conversation,lead,inbound,request,now):
    from app.modules.sales_agent import cancellation_service as c, reschedule_service as r
    from app.modules.sales_agent.first_booking import search_slots
    from app.modules.projects.locations import resolve_visit_location
    from app.modules.sales_crm.models import Meeting
    from .bp_effect_executor import _visit_starts
    visits=active_visits(db,scope,now=now)
    if len(visits)!=1 or visits[0]!=request.get('original'):
        raise ProductionToolError('The original reservation changed; nothing was changed.')
    original=visits[0];kind=request['kind']
    project=authorize_native_change(db,scope,scope.project_id)
    if kind=='cancel':
        _,meta,events=c.cancel(db,scope,conversation,lead,_native_state(),inbound,
            {'id':request['id'],'appointment':original},authorize_change=authorize_native_change)
        if not meta.get('cancellation_operation_id') or not events:raise ProductionToolError('Native cancellation did not commit.')
        return {'status':'cancelled','meeting_id':original['id'],'cancellation_operation_id':meta['cancellation_operation_id']}
    if request['unit_id']!=_property_ref(original) or request['timezone']!=project.timezone or original['duration_minutes']!=60:
        raise ProductionToolError('Replacement scope changed.')
    starts=_visit_starts(request,now)
    location=resolve_visit_location(project,original['location'])
    if not location or location['address']!=request['visit_address']:
        raise ProductionToolError('Approved replacement location changed.')
    old=db.get(Meeting,original['id'])
    context=r.target_context(db,scope,project,original['property_type_id'],original['unit_id'],location,60)
    prefs={'timezone':request['timezone'],'date_from':request['date'],'date_until':request['date'],
           'time_relation':'exact','time_from':request['start_time'],'time_until':None,'duration_minutes':60}
    options=search_slots(db,scope,prefs,now.replace(tzinfo=None),excluded_meeting=old)
    exact=[o for o in options if _utc(datetime.fromisoformat(o['starts_at']))==_utc(starts)]
    if len(exact)!=1:raise ProductionToolError('Replacement slot unavailable; original visit unchanged.')
    _,meta,events=r.replace_visit(db,scope,conversation,lead,_native_state(),inbound,
        {'id':request['id'],'original':original,'target_context':context,'option':exact[0],'preferences':prefs},
        authorize_change=lambda db,s,p:(authorize_native_change(db,s,p),s))
    if not meta.get('reschedule_operation_id') or not events:raise ProductionToolError('Native replacement did not commit.')
    return {'status':'rescheduled','original_meeting_id':original['id'],'meeting_id':meta['meeting_id'],
            'reschedule_operation_id':meta['reschedule_operation_id'],'booking_operation_id':meta['booking_operation_id']}


def execute_live_change(db,scope,*,inbound_message_id):
    """Idempotent native change and Hermes receipt in one caller transaction."""
    from .production_tools import _load_live_turn,_require_latest,_authorize_tool
    from .bp_operation_models import HermesSalesOperation
    from .bp_state_store import save
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_message_id)
    request=deepcopy(receipt.state_after.get('confirmation_request') or {})
    kind=request.get('kind')
    if kind not in TOOLS or request.get('live_change_version')!=CHANGE_VERSION:
        raise ProductionToolError('No supported live change.')
    previous=db.query(HermesSalesOperation).filter_by(**scope.__dict__,request_id=request['id']).one_or_none()
    if previous:
        if (previous.inbound_message_id!=inbound.id or previous.operation_type!=kind or previous.status!='completed'
                or previous.request_hash!=_hash(request) or (run.output_snapshot or {}).get('native_live_change',{}).get('operation_id')!=previous.id):
            raise ProductionToolError('Previous change requires reconciliation.')
        verified_change(db,scope,previous)
        return previous
    _require_latest(db,conversation,reply,receipt,loaded)
    _authorize_tool(db,run,TOOLS[kind])
    now=datetime.now(timezone.utc)
    _verify_evidence(db,scope,conversation,inbound,request,loaded.data,now)
    result=_execute_native(db,scope,conversation,lead,inbound,request,now)
    op=HermesSalesOperation(**scope.__dict__,inbound_message_id=inbound.id,request_id=request['id'],operation_type=kind,
        request_hash=_hash(request),status='completed',result_json=result)
    db.add(op);db.flush()
    verified_change(db,scope,op)
    state=deepcopy(loaded.data);state['confirmation_request']={**request,'status':'committed','result':result}
    state['last_slot_search']=None;state['last_presented_choice_set']=None
    state['visit_draft']={**(state.get('visit_draft') or {}),'status':'cancelled' if kind=='cancel' else 'confirmed'}
    revision=save(db,scope,expected_revision=loaded.revision,event_key='hei03b4:'+request['id'],state=state,event_type='state_update').revision
    run.output_snapshot={**(run.output_snapshot or {}),'native_live_change':{'operation_id':op.id,'kind':kind,
        'state_revision':revision,'business_ids':result,'delivery':'not_sent'}}
    db.flush();return op


def verified_change(db,scope,op):
    """Verify actual scoped native receipt before sending or replaying confirmation."""
    from app.modules.sales_agent.cancellation_models import SalesCancellationOperation
    from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.sales_crm.models import Meeting,MeetingStatus
    result=op.result_json or {};kind=op.operation_type
    if op.status!='completed' or kind not in TOOLS or any(getattr(op,k)!=v for k,v in scope.__dict__.items()):
        raise ProductionToolError('Change receipt is not scoped or completed.')
    def scoped(row):return bool(row and all(getattr(row,k)==v for k,v in scope.__dict__.items()))
    def meeting(mid):
        row=db.get(Meeting,mid)
        if not row or row.is_demo or row.project_id!=scope.project_id or row.lead_id!=scope.lead_id:
            raise ProductionToolError('Reservation receipt is outside scope.')
        return row
    if kind=='cancel':
        native=db.get(SalesCancellationOperation,result.get('cancellation_operation_id'))
        if (not scoped(native) or native.booking_project_id!=scope.project_id or native.proposal_id!=op.request_id
                or native.meeting_id!=result.get('meeting_id') or result.get('status')!='cancelled'):
            raise ProductionToolError('Native cancellation receipt mismatch.')
        old=meeting(native.meeting_id)
        if old.status!=MeetingStatus.CANCELLED or old.confirmation_status!='cancelled_by_lead':
            raise ProductionToolError('Cancellation status changed.')
        return f"Your visit for {_old_label(native.snapshot_json['appointment'])} has been cancelled."
    native=db.get(SalesRescheduleOperation,result.get('reschedule_operation_id'))
    booking=db.get(SalesBookingOperation,result.get('booking_operation_id'))
    if (not scoped(native) or not scoped(booking) or native.proposal_id!=op.request_id or booking.proposal_id!=op.request_id
            or native.original_meeting_id!=result.get('original_meeting_id') or native.replacement_meeting_id!=result.get('meeting_id')
            or native.replacement_booking_operation_id!=booking.id or booking.meeting_id!=native.replacement_meeting_id
            or result.get('status')!='rescheduled'):
        raise ProductionToolError('Native replacement receipt mismatch.')
    old=meeting(native.original_meeting_id);new=meeting(native.replacement_meeting_id)
    context=booking.snapshot_json['context'];option=booking.snapshot_json['option']
    if (old.status!=MeetingStatus.CANCELLED or old.confirmation_status!='rescheduled' or new.status not in {MeetingStatus.SCHEDULED,MeetingStatus.CONFIRMED}
            or _utc(new.meeting_time).isoformat()!=option['starts_at'] or new.assigned_sales_user_id!=option['sales_user_id']
            or new.duration_minutes!=context['duration_minutes'] or new.visit_address!=context['location']['address']
            or new.visit_property_type_id!=context.get('property_type_id') or new.visit_unit_id!=context.get('unit_id')):
        raise ProductionToolError('Replacement reservation changed before confirmation.')
    label=context.get('unit_code') or context.get('property_type_name') or context['project_name']
    local=_utc(new.meeting_time).astimezone(ZoneInfo(context['timezone']))
    return f'Your visit for {label} has been rescheduled to {local:%Y-%m-%d} at {local:%H:%M} ({context["timezone"]}), {new.visit_address}. Your previous reservation has been replaced.'
