"""HEI-03B: guarded native production business adapters (not a live handler).

The existing HEI-01A readiness gate remains false. A future certified live SDK
worker must supply the exact pinned, delivered turn/state receipt before any
write. No legacy orchestrator, provider calls, direct calendar calls or schema
changes. Callers own transactions; never commit an effect without its receipt.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from .engine_selection import HERMES, require_selectable

ACCEPTED = frozenset({'sent', 'delivered', 'accepted', 'read'})
LIVE_RECEIPT_PREFIX = 'hermes:live:'
LIVE_ENGINE_VERSION = 'hermes/live/1'


class ProductionToolError(PermissionError):
    """The native operation cannot be authorized or reconciled."""


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _accept_message(row, scope, channel):
    meta = (row.metadata_json or {}) if row else {}
    return bool(row and row.conversation_id == scope.conversation_id
                and row.channel == channel and row.direction == 'outbound'
                and row.role == 'assistant' and row.status in ACCEPTED
                and row.provider_message_id and meta.get('outbound_message_id')
                and meta.get('lead_id') == scope.lead_id
                and meta.get('project_id') == scope.project_id)


def _verify_provider_receipt(db, row, scope, channel):
    from app.modules.sales_agent.models import OutboundMessage
    if not _accept_message(row, scope, channel):
        raise ProductionToolError('Exact accepted provider message required.')
    out = db.get(OutboundMessage, row.metadata_json['outbound_message_id'])
    if (not out or out.conversation_id != scope.conversation_id or out.channel != channel
            or out.status not in ACCEPTED or out.provider_message_id != row.provider_message_id
            or out.content != row.content):
        raise ProductionToolError('Provider receipt does not match the visible message.')
    return out


def _authorize_tool(db, run, tool):
    from .staff_config import snapshot
    from .staged_runtime import _policy
    current = snapshot(db)
    pinned = _policy(db, run.prompt_configuration_id)
    if (not current['configuration'].get('enabled') or not current['published_version_id']
            or tool not in pinned.enabled_tools
            or tool not in current['configuration'].get('enabled_tools', ())
            or not any(isinstance(x, dict) and x.get('tool') == tool and x.get('status') == 'executed'
                       for x in (run.output_snapshot or {}).get('tool_observations', []))):
        raise ProductionToolError('Pinned and current tool permissions and an executed observation are required.')


def _load_live_turn(db, scope, inbound_id):
    """Future live worker boundary: verify every ID, provider receipt and revision.

    Gate is checked before any DB access. Staged P08 receipts cannot pass this
    contract. Row locks must be held until the caller commits or rolls back.
    Only a single-part accepted provisional reply is supported in this release.
    """
    require_selectable(HERMES)
    from app.modules.sales_agent.models import AgentRun, SalesConversation, SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    from app.modules.sales_agent.continuity import check_epoch
    from app.modules.sales_crm.models import Lead
    from app.modules.onboarding_versions import require_capability,active_approved
    from .bp_context import require_scoped_entities
    from .bp_models import HermesSalesState, HermesSalesStateEvent
    from .bp_state_store import load

    conversation = db.query(SalesConversation).filter_by(id=scope.conversation_id,
        company_id=scope.company_id, project_id=scope.project_id, lead_id=scope.lead_id
        ).populate_existing().with_for_update().one_or_none()
    if not conversation or conversation.channel not in {'sms', 'whatsapp'}:
        raise ProductionToolError('A scoped live Sales conversation is required.')
    db.query(Lead).filter_by(id=scope.lead_id, company_id=scope.company_id,
        project_id=scope.project_id).populate_existing().with_for_update().one()
    _, project, lead, conversation = require_scoped_entities(db, scope)
    if (lead.is_demo or project.is_demo or lead.deleted_at or lead.is_opt_out or lead.consent_status != 'granted'
            or lead.agent_status == 'human_control' or conversation.is_paused):
        raise ProductionToolError('Live buyer authorization is not active.')
    if not active_approved(project.profile):
        raise ProductionToolError('Project approval was withdrawn before commercial execution.')
    require_capability(project.profile)
    inbound = scoped_messages_query(db, conversation).filter_by(id=inbound_id,
        channel=conversation.channel, direction='inbound', role='user').one_or_none()
    if not inbound or not inbound.provider_message_id or (inbound.metadata_json or {}).get('lead_id') != scope.lead_id:
        raise ProductionToolError('A persisted, scoped provider inbound is required.')
    pin = (inbound.metadata_json or {}).get(PIN_KEY) or {}
    event = pin.get('event_id')
    if not isinstance(event, str) or not event or any(pin.get(k) != v for k,v in event_scope(conversation,event).items()) or pin.get('engine') != HERMES:
        raise ProductionToolError('The event must belong to the live Hermes lane.')
    run = db.query(AgentRun).filter_by(event_id=event, conversation_id=conversation.id
        ).populate_existing().with_for_update().one_or_none()
    if (not run or run.graph_version != LIVE_ENGINE_VERSION or run.mode != 'live'
            or run.status != 'completed' or not run.prompt_configuration_id
            or run.prompt_configuration_id != pin.get('policy_version_id')
            or (run.input_snapshot or {}).get(PIN_KEY) != pin
            or (run.input_snapshot or {}).get('message_id') != inbound.id):
        raise ProductionToolError('A completed, pinned live Hermes run is required.')
    if (run.input_snapshot or {}).get('continuity_epoch') is None:
        raise ProductionToolError('Live continuity epoch is required.')
    check_epoch(conversation, run.input_snapshot['continuity_epoch'])
    meta = (run.output_snapshot or {}).get('metadata') or {}
    row = scoped_messages_query(db, conversation).filter_by(id=meta.get('message_id')).one_or_none()
    out = _verify_provider_receipt(db, row, scope, conversation.channel)
    if (out.agent_run_id != run.id or (row.metadata_json or {}).get('agent_run_id') != run.id
            or (row.metadata_json or {}).get('hermes_inbound_message_id') != inbound.id
            or (row.metadata_json or {}).get('engine') != 'hermes-agent'
            or (run.output_snapshot or {}).get('reply') != row.content
            or (row.created_at,row.id) <= (inbound.created_at,inbound.id)
            or ((row.metadata_json or {}).get('delivery_group') or {}).get('total',1) != 1):
        raise ProductionToolError('Original accepted Hermes reply cannot be verified.')
    db.query(HermesSalesState).filter_by(**scope.__dict__).populate_existing().with_for_update().all()
    receipt = db.query(HermesSalesStateEvent).filter_by(**scope.__dict__,
        event_key=LIVE_RECEIPT_PREFIX+inbound.id, event_type='outbound_choice_receipt').one_or_none()
    loaded = load(db,scope)
    if (not receipt or meta.get('state_revision') != receipt.revision
            or not isinstance(receipt.state_after,dict) or receipt.payload_hash!=_hash(receipt.state_after)):
        raise ProductionToolError('The delivered live state receipt is missing.')
    return conversation, project, lead, inbound, run, row, receipt, loaded


def _require_latest(db, conversation, row, receipt, loaded):
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    latest = scoped_messages_query(db,conversation).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).first()
    if (not latest or latest.id != row.id or loaded.revision != receipt.revision
            or loaded.data != receipt.state_after):
        raise ProductionToolError('Newer conversation evidence supersedes this proposal.')


def _resolve_property(db, scope, project, reference, channel, *, require_available=False):
    """Resolve from the current approved catalog, never raw onboarding drafts."""
    from app.modules.sales_agent.commercial_context import build_commercial_context
    commercial = build_commercial_context(db,project=project,company_id=scope.company_id,
                                           lead_id=scope.lead_id,channel=channel)
    units = [r for r in commercial.get('inventory',[]) if commercial.get('inventory_source')=='individual_units'
             and reference in (r.get('id'),r.get('unit_code'))]
    types = [r for r in commercial.get('property_types',[]) if reference == r.get('id')]
    if len(units)+len(types)!=1:
        raise ProductionToolError('Property is missing or ambiguous in the approved catalog.')
    if units:
        row=units[0]
        if require_available and (row.get('status') not in {'available','ready','active'} or not row.get('inventory_updated_at')):
            raise ProductionToolError('The selected unit is no longer verified as available.')
        return None,row['id'],row['unit_code']
    row=types[0]
    if require_available and row.get('available_units') == 0 and row.get('inventory_updated_at'):
        raise ProductionToolError('The selected property type is no longer available.')
    return row['id'],None,row['property_type']


def calendar_snapshot(meeting, request, advisor):
    """Exact format consumed by first_booking.sync_calendar, NOT P04 demo JSON."""
    context = deepcopy(meeting.visit_context or {})
    if (not context.get('project_name') or context.get('timezone') != request['timezone']
            or meeting.assigned_sales_user_id != advisor.id or meeting.is_demo
            or meeting.duration_minutes != 60 or not meeting.visit_address
            or meeting.visit_address != request.get('visit_address')
            or _utc(meeting.meeting_time).isoformat() != _utc(datetime.fromisoformat(request['starts_at_utc'])).isoformat()):
        raise ProductionToolError('Native booking receipt does not match the committed visit.')
    return {'context':{**context,'location':{'label':meeting.visit_location_label,'address':meeting.visit_address},
                       'duration_minutes':meeting.duration_minutes},
            'option':{'starts_at':_utc(meeting.meeting_time).isoformat(),'sales_user_id':advisor.id},
            'preferences':{'duration_minutes':meeting.duration_minutes,'timezone':request['timezone']}}


def _book(db, scope, project, lead, conversation, request, now):
    from app.modules.onboarding_versions import require_capability
    from app.modules.projects.locations import resolve_visit_location
    from app.modules.sales_crm.scheduling import create_agent_appointment
    from app.modules.sales_agent.first_booking import active_meetings
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.sales_agent.models import SalesFollowUpJob
    from .bp_effect_executor import _visit_starts
    require_capability(project.profile,'appointments')
    if request.get('timezone') != project.timezone:
        raise ProductionToolError('The project timezone changed; request a new recap.')
    if active_meetings(db,scope,now.replace(tzinfo=None)):
        raise ProductionToolError('An active real appointment already exists.')
    property_id,unit_id,name = _resolve_property(db,scope,project,request['unit_id'],conversation.channel,require_available=True)
    location = resolve_visit_location(project)
    # P04 has no durable location selection. Require the exact approved location
    # in the recap before enabling production; a project with ambiguity blocks.
    if not location or request.get('visit_address') != location['address']:
        raise ProductionToolError('The exact approved visit location must be confirmed first.')
    starts = _visit_starts(request,now)
    meeting,advisor = create_agent_appointment(db,lead=lead,starts_at=starts,duration_minutes=60,
        modality='showroom',visit_location=location,defer_calendar=True,capture_visit_context=True,
        visit_property_type_id=property_id,visit_unit_id=unit_id,booking_project_id=scope.project_id)
    if (meeting.project_id != scope.project_id or meeting.lead_id != scope.lead_id
            or meeting.visit_property_type_id != property_id or meeting.visit_unit_id != unit_id):
        raise ProductionToolError('Scheduling returned a foreign or mismatched visit.')
    snapshot = calendar_snapshot(meeting,request,advisor)
    op = SalesBookingOperation(**scope.__dict__,proposal_id=request['id'],meeting_id=meeting.id,
        snapshot_json=snapshot,calendar_status='pending',next_attempt_at=now.replace(tzinfo=None))
    db.add(op);db.flush()
    conversation.stage='appointment_confirmed'
    lead.agent_status='appointment_confirmed'
    lead.next_action_at=None
    for job in db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id).filter(
            SalesFollowUpJob.status.in_(['pending','processing'])).all():
        if (job.reason or '').endswith('_cadence'):
            job.status='cancelled'
    return {'status':'confirmed','meeting_id':meeting.id,'booking_operation_id':op.id,
            'calendar_status':'pending','delivery':'not_sent','property_name':name}


def _validate_booking_evidence(db, scope, conversation, inbound, state, now):
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from .bp_effect_executor import _accepted_request
    from .bp_operation_receipts import recap_visible
    from .bp_operational_port import _fresh
    request = deepcopy(state.get('confirmation_request') or {})
    if request.get('kind')!='book' or request.get('confirmed_inbound_message_id')!=inbound.id:
        raise ProductionToolError('No first-visit request for this turn.')
    from .journey_contract import booking_consent
    from .bp_operation_receipts import evidence_live_inbound
    from .bp_operational_port import AFFIRMATIVE
    if AFFIRMATIVE.fullmatch(inbound.content):
        _accepted_request(db,scope,request,inbound.id,now=now)
    else:
        # Additional explicit variants use the same scoped, persisted recap proof.
        if not (_fresh(request,now) and request.get('status')=='execution_requested'
                and request.get('recap_message_id') and booking_consent(inbound.content)):
            raise ProductionToolError('Explicit booking confirmation is required.')
        evidence_live_inbound(db,scope,inbound.id,after_reply_message_id=request['recap_message_id'])
    offer=state.get('last_slot_search') or {}
    if (not _fresh(offer,now) or offer.get('project_id')!=scope.project_id
            or offer.get('proposal_id')!=request.get('proposal_id') or offer.get('unit_id')!=request.get('unit_id')
            or offer.get('timezone')!=request.get('timezone') or not any(
                all(x.get(k)==request.get(k) for k in ('starts_at_utc','date','start_time'))
                for x in offer.get('options',[]))):
        raise ProductionToolError('No fresh exact slot offer for this request.')
    q=scoped_messages_query(db,conversation)
    offered=q.filter_by(id=offer.get('source_reply_message_id')).one_or_none()
    recap=q.filter_by(id=request.get('recap_message_id')).one_or_none()
    _verify_provider_receipt(db,offered,scope,conversation.channel)
    _verify_provider_receipt(db,recap,scope,conversation.channel)
    from .contextual_choices import _date_label, _time_label
    # The selected time must be visible in the delivered offer, not only in
    # hidden tool output. An exact recap is required immediately before assent.
    offered_text=offered.content.casefold()
    visible_record = {'unit_id':request['unit_id']}
    if offer.get('menu_kind'):
        from .bp_context import require_scoped_entities
        from .bp_operation_receipts import _property_visible
        _, project, _, _ = require_scoped_entities(db,scope)
        property_id, unit_id, verified_name = _resolve_property(db,scope,project,request['unit_id'],conversation.channel)
        # Individual inventory may render the approved type plus its unit code.
        # Require the exact verified unit code, not the database UUID.
        label = request.get('display_name') or ''
        name_matches = (label == verified_name if property_id else
                        bool(re.search(r'(?<![\w-])'+re.escape(verified_name)+r'(?![\w-])',label,re.I)))
        if (offer['menu_kind']!='visit_time' or not name_matches):
            raise ProductionToolError('A verified property and exact-day time offer are required.')
        visible_record['display_name']=label
        visible_property=_property_visible(offered.content,visible_record)
        # The selected start must be a numbered option, not incidental prose.
        if not any(re.fullmatch(r'\s*[1-9][.)]\s+'+re.escape(_time_label(request['start_time']))+r'\s*',line,re.I)
                   for line in offered.content.splitlines()):
            raise ProductionToolError('The selected start time was not a visible option.')
    else:
        visible_property=str(request['unit_id']).casefold() in offered_text
    if (not visible_property
            or not any(v.casefold() in offered_text for v in (request['date'],_date_label(request['date'])))
            or not any(v.casefold() in offered_text for v in (request['start_time'],_time_label(request['start_time'])))):
        raise ProductionToolError('The selected slot was not visible in the accepted offer.')
    latest_before=q.filter(SalesMessage.created_at <= inbound.created_at, SalesMessage.id != inbound.id).order_by(
        SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    if not latest_before or latest_before.id!=recap.id:
        raise ProductionToolError('Confirmation must immediately follow the accepted recap.')
    address=request.get('visit_address')
    if (not recap_visible(recap.content,request) or not isinstance(address,str) or not address.strip()
            or address.casefold() not in recap.content.casefold()
            or request['timezone'].casefold() not in recap.content.casefold()
            or not (offered.created_at,offered.id)<(recap.created_at,recap.id)<(inbound.created_at,inbound.id)):
        raise ProductionToolError('Full property/date/time/timezone/location recap was not accepted.')
    return request


def execute_first_live_booking(db, scope, *, inbound_message_id):
    """Guarded native booking + durable operation, caller owns transaction.

    No provider send and no direct Calendar sync. A future live handler must
    reconcile the persisted operation and deliver the confirmation via existing
    messaging. Never invoke from a route until the live runtime is certified.
    """
    conversation, project, lead, inbound, run, reply, receipt, loaded = _load_live_turn(db,scope,inbound_message_id)
    from .bp_operation_models import HermesSalesOperation
    from .bp_state_store import save
    from .native_effects import _assert_business_policy
    existing=db.query(HermesSalesOperation).filter_by(**scope.__dict__,inbound_message_id=inbound.id,
        operation_type='book').all()
    if existing:
        if len(existing)!=1 or existing[0].status!='completed':
            raise ProductionToolError('Prior native operation requires reconciliation.')
        op=existing[0]; result=deepcopy(op.result_json or {})
        from app.modules.sales_agent.booking_models import SalesBookingOperation
        booking=db.get(SalesBookingOperation,result.get('booking_operation_id'))
        original_request=receipt.state_after.get('confirmation_request') or {}
        if (not booking or booking.meeting_id!=result.get('meeting_id') or booking.proposal_id!=op.request_id
                or op.request_hash!=_hash(original_request) or original_request.get('id')!=op.request_id
                or result.get('status')!='confirmed'
                or ((run.output_snapshot or {}).get('native_live_booking') or {}).get('operation_id')!=op.id
                or any(getattr(booking,k)!=v for k,v in scope.__dict__.items())):
            raise ProductionToolError('Stored booking operation requires reconciliation.')
        return {**result,'operation_id':op.id,'replayed':True,'historical_receipt':True}
    _require_latest(db,conversation,reply,receipt,loaded)
    _authorize_tool(db,run,'book_onsite_visit')
    _assert_business_policy(db,scope,'book')
    now=datetime.now(timezone.utc)
    request=_validate_booking_evidence(db,scope,conversation,inbound,loaded.data,now)
    result=_book(db,scope,project,lead,conversation,request,now)
    op=HermesSalesOperation(**scope.__dict__,inbound_message_id=inbound.id,request_id=request['id'],
        operation_type='book',request_hash=_hash(request),status='completed',result_json=result)
    db.add(op);db.flush()
    state=deepcopy(loaded.data)
    state['confirmation_request']={**request,'status':'committed','result':result}
    state['visit_draft']={**(state.get('visit_draft') or {}),'status':'confirmed'}
    state['conversation_phase']='appointment_confirmed'
    state['visit_planning_paused']=False
    revision=save(db,scope,expected_revision=loaded.revision,event_key='hei03b:'+request['id'],
        state=state,event_type='state_update').revision
    run.output_snapshot={**(run.output_snapshot or {}),'native_live_booking':{'operation_id':op.id,
        'state_revision':revision,'business_ids':{'meeting_id':result['meeting_id'],
        'booking_operation_id':result['booking_operation_id']},'calendar_status':'pending','delivery':'not_sent'}}
    db.flush()
    return {**result,'operation_id':op.id,'replayed':False}


def _material_batch(db, scope, project, channel, draft, now):
    """Resolve a bounded, all-or-nothing batch of exact approved file bindings.

    Does not mint access tokens. The future dispatch coordinator must bind each
    share to the durable outbox and revalidate snapshots before every send.
    URL-only galleries use exact reviewed HTTPS targets; no remote fetch.
    """
    from app.modules.projects.models import ProjectSalesAsset
    from app.modules.projects.sales_asset_service import approved_for_turn
    from app.modules.projects.asset_coverage import matches
    from app.modules.sales_agent.material_delivery import snapshot
    from .bp_operational_port import _fresh
    from .live_multi_material import subject_mapping
    ids=draft.get('asset_ids')
    if channel not in {'sms','whatsapp'} or not _fresh(draft,now):
        raise ProductionToolError('Invalid or expired requested material batch.')
    subjects=subject_mapping(draft)
    prop,unit,_=_resolve_property(db,scope,project,draft.get('unit_id'),channel)
    approved={a.id for a in approved_for_turn(db,project_id=scope.project_id,company_id=scope.company_id,channel=channel)}
    if not set(ids)<=approved:
        raise ProductionToolError('One or more requested assets are no longer approved.')
    bindings=[]
    for asset_id in ids:
        asset=db.query(ProjectSalesAsset).filter_by(id=asset_id,company_id=scope.company_id,
            project_id=scope.project_id).populate_existing().with_for_update().one_or_none()
        if not asset or not all(any(x.get('coverage')=='requested_tag' for x in matches(asset,
                property_id=prop,unit_id=unit,subject='photos' if tag=='gallery_image' else tag)) for tag in subjects[asset_id]):
            raise ProductionToolError('Material does not cover the requested property and subject.')
        source=getattr(asset,'source',None)
        if source is not None and not source.storage_path:
            if subjects[asset_id]!=['gallery_image']:
                raise ProductionToolError('External resources must be reviewed gallery targets.')
            from app.modules.sales_agent.commercial_context import _safe_asset_links
            from urllib.parse import urlsplit
            targets=sorted({item['url'] for item in _safe_asset_links(asset)
                            if item['kind'] in {'photos','gallery_image'} and urlsplit(item['url']).scheme=='https'})
            if not targets:
                raise ProductionToolError('No approved external gallery target is available.')
            bindings.extend(snapshot(asset,channel=channel,target_url=target) for target in targets)
        else:
            bindings.append(snapshot(asset,channel=channel))
        if len(bindings)>20:
            raise ProductionToolError('Material resource limit exceeded; narrow the request.')
    return bindings


def prepare_live_material_batch(db, scope, *, inbound_message_id):
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_message_id)
    from .native_effects import _assert_business_policy
    _require_latest(db,conversation,reply,receipt,loaded)
    _authorize_tool(db,run,'get_unit_media')
    _assert_business_policy(db,scope,'material')
    draft=(loaded.data.get('offered_assets') or {}).get('pending_request') or {}
    if draft.get('source_inbound_message_id')!=inbound.id:
        raise ProductionToolError('No requested materials for this inbound.')
    # Same exact subject or generic PDF with an already verified single document
    # type; a bare assent must be handled by a future delivered-offer contract.
    from .conversation_parity import media_tags
    tags=media_tags(inbound.content)
    if draft.get('subjects') is not None:
        from .live_multi_material import explicit_multi_subjects
        if explicit_multi_subjects(inbound.content)!=draft.get('subjects'):
            raise ProductionToolError('Explicit multi-subject material evidence is required.')
    elif tags!=[draft.get('subject')] and not (not tags and re.search(r'\bpdf\b',inbound.content,re.I)
            and draft.get('subject')!='gallery_image' and len(draft.get('asset_ids') or [])==1):
        raise ProductionToolError('Explicit material evidence is required.')
    bindings=_material_batch(db,scope,project,conversation.channel,draft,datetime.now(timezone.utc))
    return {'request_id':draft['id'],'bindings':bindings,'delivery':'not_sent'}


# Narrow English direct declarations only. Broader, ambiguous, third-party,
# exploratory, multi-fact or non-USD statements stay conversational until the
# CRM evidence contract has a supported interpretation. No second LLM.
_MONEY = r'(?:USD\s*\$?\s*|US\$\s*|\$\s*)\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|(?:USD\s*\$?\s*|US\$\s*|\$\s*)\d+(?:\.\d+)?(?:\s*[kKmM])?'
_BUDGET = re.compile(r'(?:actually,?\s+)?(?:my|our)\s+(?:(?:new|maximum|max|minimum|min)\s+){0,2}budget\s+is\s+(?:about\s+|around\s+|up to\s+|at most\s+|at least\s+)?(?P<amount>'+_MONEY+r')\s*[.!]?$',re.I)
_BEDROOMS = re.compile(r'(?:actually,?\s+)?(?:i|we)\s+(?:now\s+)?(?:need|want|prefer|require)\s+(?:a\s+(?:house|home|property)\s+with\s+)?(?:exactly\s+|at least\s+|at most\s+)?(?:[1-9]|1\d|20)\s+bedrooms?\s*[.!]?$',re.I)


def direct_profile_values(text, preferences, *, project_currency=None):
    """Convert only buyer-evidenced and state-agreeing permanent preferences."""
    from .sales_preferences import parse_declarations
    from .commercial_turn import scope as preference_scope
    text=text.strip()
    budget_match=_BUDGET.fullmatch(text)
    bedroom_match=_BEDROOMS.fullmatch(text)
    if not budget_match and not bedroom_match:
        return {}
    if budget_match and budget_match['amount'].startswith('$') and str(project_currency or '').upper()!='USD':
        return {}
    if preference_scope(text, True)!='permanent':
        return {}
    declarations=parse_declarations(text)
    if budget_match:
        value=declarations.get('budget') or {}
        saved=preferences.get('budget') or {}
        if not value or any(saved.get(k)!=v for k,v in value.items()):return {}
        mode=value.get('mode')
        if mode not in {'cap','floor','target','fixed_funds'}:return {}
        amount=value.get('maximum_usd') or value.get('minimum_usd') or value.get('target_usd')
        from decimal import Decimal, InvalidOperation
        token=re.sub(r'^(?:USD\s*\$?\s*|US\$\s*|\$\s*)','',budget_match['amount'],flags=re.I).replace(',','').strip()
        multiplier=Decimal(1000 if token.lower().endswith('k') else 1000000 if token.lower().endswith('m') else 1)
        try: exact=Decimal(token.rstrip('kKmM').strip())*multiplier
        except InvalidOperation:return {}
        if type(amount) is not int or not 0<amount<100_000_000 or exact!=amount:return {}
        if mode in {'cap','target','fixed_funds'} and saved.get('minimum_usd') is not None:return {}
        if mode in {'floor','target'} and saved.get('maximum_usd') is not None:return {}
        # CRM budget retains exact declared meaning; never claim verified funds.
        # Explicitly clear obsolete limits in the existing profile on replacement.
        return {'budget':text,'budget_currency':'USD',
                'budget_minimum':saved.get('minimum_usd'),'budget_maximum':saved.get('maximum_usd')}
    value=declarations.get('bedrooms') or {};saved=preferences.get('bedrooms') or {}
    if not value or any(saved.get(k)!=v for k,v in value.items()):return {}
    if value.get('mode') in {'exact','preferred'} and type(value.get('preferred')) is int:
        return {'bedrooms':value['preferred']}
    # Minimum/maximum are not exact counts; preserve the actual declaration.
    if value.get('mode') in {'minimum','maximum'}:return {'bedrooms':text}
    return {}


def _write_profile(db, lead, inbound, values):
    """Use existing CRM record/version/compatibility-fact shape, not a new store."""
    from app.modules.sales_agent import lead_profile
    from app.modules.sales_crm.intelligence import lead_profile_summary
    resolved=lead_profile.resolve(lead)
    current=deepcopy(resolved['current']);history=deepcopy(resolved['history'])
    updated=[]
    for field,value in values.items():
        previous=current[field]
        # Never treat a self-declaration as verification; do not overwrite
        # separately staff-verified information without explicit staff review.
        if previous.get('source')=='staff_verified' and previous.get('status')=='confirmed':
            raise ProductionToolError('A staff-verified CRM field requires review before replacement.')
        if value is None and previous.get('status') in {'unknown','withdrawn'}:continue
        item=lead_profile.record(field,value,source='active_conversation',at=inbound.created_at,
            evidence=inbound.content,source_ref={'message_id':inbound.id},status='withdrawn' if value is None else 'declared')
        if item['id']==previous.get('id'):continue
        if previous.get('status')!='unknown' and previous.get('id') not in {x.get('id') for x in history}:
            history.append(previous)
        item['supersedes']=previous.get('id') if previous.get('status')!='unknown' else None
        current[field]=item;updated.append(field)
    if not updated:return []
    profile=deepcopy(lead.lead_profile_data or {})
    explicit={field:item for field,item in current.items() if item.get('source') in
              {'active_conversation','approved_catalog_selection','staff_verified'}}
    profile['sales_profile']={'version':lead_profile.VERSION,'current':explicit,'history':history[-100:]}
    facts=profile.setdefault('facts',{})
    for field in updated:
        item=current[field]
        if item['status']=='withdrawn':facts.pop(field,None)
        else:facts[field]={'value':item['value'],'source':item['source'],'status':item['status'],'confirmed':False,
            'captured_at':item['captured_at'],'evidence':item['evidence'],'message_id':inbound.id}
    lead.lead_profile_data=profile
    lead.qualification_summary=lead_profile_summary({'facts':{f:{'value':r['value']} for f,r in current.items()
        if r['status'] in {'declared','confirmed'}}})
    db.flush()
    return updated


def persist_live_preferences(db, scope, *, inbound_message_id):
    """Persist narrow evidenced declarations using the existing Lead JSON schema.

    Caller owns commit/rollback. No speculative identity, lead score, segment,
    demographics or purchase timeline inference. No new table or column.
    """
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_message_id)
    from app.modules.sales_agent.commercial_context import confirmed_profile_facts
    from app.modules.governance.services import request_attribution
    from app.modules.sales_agent.lead_profile import own_statement
    _require_latest(db,conversation,reply,receipt,loaded)
    _authorize_tool(db,run,'update_search_preferences')
    preferences=loaded.data.get('search_preferences') or {}
    if preferences.get('last_source_message_id')!=inbound.id:
        raise ProductionToolError('No permanent preference revision from this inbound.')
    if not own_statement(inbound.content,request_attribution(inbound.content)['current_text']):
        raise ProductionToolError('Only the current buyer self-declaration may update the profile.')
    values=direct_profile_values(inbound.content,preferences,
        project_currency=confirmed_profile_facts(project.profile).get('currency'))
    if not values:
        return {'status':'no_supported_declaration','updated_fields':[]}
    fields=_write_profile(db,lead,inbound,values)
    run.output_snapshot={**(run.output_snapshot or {}),'native_live_profile':{
        'source_message_id':inbound.id,'updated_fields':fields or
            ((run.output_snapshot or {}).get('native_live_profile') or {}).get('updated_fields',[])}}
    db.flush()
    return {'status':'persisted' if fields else 'unchanged','updated_fields':fields}


def material_delivery_receipt(db, scope, *, message_ids, expected_share_ids, channel):
    """Read exact provider/outbox/share correlation, without exposing bearer URLs.

    Does not send or retry a provider call. Acceptance is not device delivery.
    Future live dispatch integration calls this only after its normal outbox path.
    """
    require_selectable(HERMES)
    from app.modules.projects.models import SalesAssetShare
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from .bp_context import require_scoped_entities
    _,_,_,conversation=require_scoped_entities(db,scope)
    if conversation.channel!=channel or channel not in {'sms','whatsapp'}:
        raise ProductionToolError('Invalid receipt channel.')
    if (not isinstance(message_ids,list) or not isinstance(expected_share_ids,list)
            or not 1<=len(message_ids)<=40 or not 1<=len(expected_share_ids)<=20
            or any(not isinstance(x,str) or not x for x in message_ids+expected_share_ids)
            or len(set(message_ids))!=len(message_ids) or len(set(expected_share_ids))!=len(expected_share_ids)):
        raise ProductionToolError('Invalid receipt identifiers.')
    from app.modules.sales_agent.material_delivery import validate_shares
    found=set();parts=[];group_key=None;run_id=None
    for mid in message_ids:
        row=scoped_messages_query(db,conversation).filter_by(id=mid).one_or_none()
        out=_verify_provider_receipt(db,row,scope,channel)
        meta=row.metadata_json or {}; group=meta.get('delivery_group') or {}
        if (meta.get('engine')!='hermes-agent' or not out.agent_run_id or meta.get('agent_run_id')!=out.agent_run_id
                or not group.get('key') or group.get('total')!=len(message_ids)
                or type(group.get('part')) is not int):
            raise ProductionToolError('Incomplete or inconsistent Hermes delivery group.')
        if group_key is None:group_key=group['key'];run_id=out.agent_run_id
        if group['key']!=group_key or out.agent_run_id!=run_id:
            raise ProductionToolError('Mixed delivery groups cannot form a receipt.')
        ids=meta.get('sales_asset_share_ids') or []
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids) or len(ids)!=len(set(ids)) or found.intersection(ids):
            raise ProductionToolError('Invalid material part attribution.')
        shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(ids)).all() if ids else []
        if (len(shares)!=len(ids) or any(s.company_id!=scope.company_id or s.project_id!=scope.project_id
                or s.lead_id!=scope.lead_id or s.channel!=channel or s.agent_run_id!=run_id
                or s.outbound_message_id!=out.id for s in shares)):
            raise ProductionToolError('Asset share is not bound to this provider outbox.')
        # The existing dispatcher matches the actual bearer token hash to each
        # part; re-check rather than trusting metadata or returning the token.
        hashes={sha256(t.rstrip('.,;)').encode()).hexdigest() for t in re.findall(r'/projects/a/([^\s]+)',row.content)}
        if any(s.token_hash not in hashes for s in shares):
            raise ProductionToolError('A share was not actually present in the accepted message.')
        if shares and not validate_shares(db,scope,shares,meta,subset=True):
            raise ProductionToolError('A material binding changed or expired.')
        found.update(ids);parts.append((group['part'],row.status,out.status))
    if found!=set(expected_share_ids) or sorted(p[0] for p in parts)!=list(range(1,len(message_ids)+1)):
        raise ProductionToolError('Not every expected share and message part was accepted.')
    delivered=all(a in {'delivered','read'} and b in {'delivered','read'} for _,a,b in parts)
    return {'status':'delivered' if delivered else 'provider_accepted','message_ids':list(message_ids),
            'share_ids':list(expected_share_ids),'agent_run_id':run_id}
