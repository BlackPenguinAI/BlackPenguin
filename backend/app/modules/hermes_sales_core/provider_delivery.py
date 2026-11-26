"""HEI-03B.3: Hermes authorization and reconciliation for the shared dispatcher.

No provider calls here. Plans contain hashes, never bearer URLs. Every provider
part is authorized again under the existing conversation lock. Ambiguous
receipts are reconciled or reviewed, never resent automatically.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import re

from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, LIVE_ENGINE_VERSION, ACCEPTED

ENGINE = 'hermes-agent'
CONTROL_ENGINE = 'hermes-control/1'
STOP_REPLY = 'You have been unsubscribed and will not receive further messages.'
HANDOFF_REPLY = 'Your request has been recorded for the Sales team to review.'


class ReceiptPending(RuntimeError):
    """Provider has a durable identifier, but final acceptance is not known."""


def digest_text(text):
    return sha256(text.encode('utf-8')).hexdigest()


def part_key(key, part, total):
    return key if total == 1 else f'{key}:part:{part}'


def verify_plan_part(plan, metadata, content, key):
    group = metadata.get('delivery_group') or {}
    parts = plan.get('parts') or []
    index = group.get('part')
    if (not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= len(parts)
            or group.get('total') != len(parts) or group.get('key') != plan.get('key')
            or key != part_key(plan['key'], index, len(parts))
            or digest_text(content) != parts[index-1]['sha256']
            or sorted(metadata.get('sales_asset_share_ids') or []) != parts[index-1]['share_ids']):
        raise ProductionToolError('Dispatch does not match the exact authorized Hermes plan.')
    return parts[index-1]


def build_plan(key, kind, content, channel, *, share_hashes=None, operation_id=None):
    from app.modules.sales_agent.response_policy import render_channel_text, split_channel_text
    if kind not in {'reply', 'material', 'booking', 'cancel', 'reschedule'} or not isinstance(key,str) or not key.startswith('hermes:'):
        raise ProductionToolError('Unsupported Hermes delivery plan.')
    canonical = render_channel_text(content, channel)
    parts = split_channel_text(canonical, channel)
    if not parts or len(parts)>40 or (kind not in {'material','reply'} and parts != [canonical]):
        raise ProductionToolError('Unsupported Hermes delivery partition.')
    share_hashes = share_hashes or {}
    if kind != 'material' and share_hashes:
        raise ProductionToolError('Unexpected material IDs.')
    seen=set(); result=[]
    for text in parts:
        hashes = {digest_text(x.rstrip('.,;)')) for x in re.findall(r'/projects/a/([^\s]+)',text)}
        ids = sorted(sid for sid,h in share_hashes.items() if h in hashes)
        if seen.intersection(ids) or hashes != {share_hashes[i] for i in ids}:
            raise ProductionToolError('An opaque link is not bound to an authorized share.')
        seen.update(ids); result.append({'sha256':digest_text(text),'share_ids':ids})
    if seen != set(share_hashes):
        raise ProductionToolError('Not all issued shares are present in the delivery plan.')
    return canonical, {'key':key,'kind':kind,'operation_id':operation_id,'parts':result}


def record_plan(db, run, conversation, delivery, *, kind, operation_id=None):
    """Register exact per-part content hashes before the outbox is written."""
    require_selectable(HERMES)
    from app.modules.projects.models import SalesAssetShare
    ids=delivery['metadata'].get('sales_asset_share_ids') or []
    shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(ids)).all() if ids else []
    if (len(shares)!=len(ids) or any(s.agent_run_id!=run.id or s.company_id!=conversation.company_id
            or s.project_id!=conversation.project_id or s.lead_id!=conversation.lead_id
            or s.channel!=conversation.channel for s in shares)):
        raise ProductionToolError('Share scope changed before dispatch planning.')
    content,plan=build_plan(delivery['idempotency_key'],kind,delivery['content'],conversation.channel,
        share_hashes={s.id:s.token_hash for s in shares},operation_id=operation_id)
    if kind=='reply' and len(plan['parts'])>1:
        from .live_coordinator import restore_draft
        from .multipart_reply import reply_parts
        from .contracts import TurnScope
        scope=TurnScope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
        turn=restore_draft((run.output_snapshot or {}).get('live_draft'),scope,(run.input_snapshot or {}).get('message_id'))
        reply_parts(turn,conversation.channel)
        if content!=turn.prepared.result.reply:
            raise ProductionToolError('Multipart content changed before planning.')
    output=deepcopy(run.output_snapshot or {}); plans=output.setdefault('hermes_delivery_plans',{})
    if plan['key'] in plans and plans[plan['key']]!=plan:
        raise ProductionToolError('Immutable delivery plan changed.')
    if len(plans)>=4 and plan['key'] not in plans:
        raise ProductionToolError('Too many delivery groups for this turn.')
    plans[plan['key']]=plan;run.output_snapshot=output;db.flush()
    return {**delivery,'content':content,'metadata':{**delivery['metadata'],'hermes_delivery_kind':kind}},plan


def _base(db, conversation, lead, metadata):
    """Scope/pin/epoch checks for both model and deterministic control sends."""
    from .contracts import TurnScope
    from .bp_context import require_scoped_entities
    from app.modules.sales_agent.models import SalesConversation,SalesMessage
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.continuity import check_epoch
    from app.modules.sales_agent.engine_router import event_scope,PIN_KEY
    require_selectable(HERMES)
    scope=TurnScope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    db.query(SalesConversation).filter_by(id=scope.conversation_id).populate_existing().with_for_update().one()
    db.query(Lead).filter_by(id=scope.lead_id).populate_existing().with_for_update().one()
    _,project,fresh,conversation=require_scoped_entities(db,scope)
    if (fresh.id!=lead.id or fresh.is_demo or project.is_demo or conversation.channel not in {'sms','whatsapp'}
            or metadata.get('lead_id')!=scope.lead_id or metadata.get('project_id')!=scope.project_id
            or metadata.get('continuity_epoch') is None):
        raise ProductionToolError('Dispatch scope is not an authorized live opportunity.')
    check_epoch(conversation,metadata['continuity_epoch'])
    inbound=scoped_messages_query(db,conversation).filter_by(id=metadata.get('hermes_inbound_message_id'),
        direction='inbound',role='user',channel=conversation.channel).one_or_none()
    if not inbound or not inbound.provider_message_id:
        raise ProductionToolError('No authenticated provider inbound.')
    pin=(inbound.metadata_json or {}).get(PIN_KEY) or {}
    if ((inbound.metadata_json or {}).get('lead_id')!=scope.lead_id
            or (inbound.metadata_json or {}).get('project_id')!=scope.project_id
            or pin.get('engine')!=HERMES or any(pin.get(k)!=v for k,v in event_scope(conversation,f'{conversation.provider}:{inbound.provider_message_id}').items())):
        raise ProductionToolError('The inbound event is not pinned to Hermes.')
    return scope,project,fresh,conversation,inbound,pin


def authorize_part(db, conversation, lead, metadata, content, key, agent_run_id):
    """Called twice by live_service: before durable enqueue and before provider."""
    from .scheduled_work import SCHEDULED_ENGINE, authorize_scheduled
    if metadata.get("engine")==SCHEDULED_ENGINE:
        return authorize_scheduled(db,conversation,lead,metadata,content,key,agent_run_id)
    from app.modules.sales_agent.models import AgentRun
    from app.modules.sales_agent.continuity import state as continuity_state
    from app.modules.onboarding_versions import require_capability,active_approved
    from .staff_config import snapshot
    from .staged_runtime import _policy
    from .bp_operation_models import HermesSalesOperation
    scope,project,lead,conversation,inbound,pin=_base(db,conversation,lead,metadata)
    if metadata.get('engine')==CONTROL_ENGINE:
        from app.modules.sales_agent.continuity_policy import explicit_opt_out,evidenced_pause_reason
        from app.modules.sales_agent.moderation import precheck
        control=(inbound.metadata_json or {}).get('hermes_control') or {}
        kind=control.get('kind')
        if (agent_run_id is not None or key!='hermes:control:'+inbound.id or
                metadata.get('control_outcome')!=kind or control.get('epoch')!=metadata['continuity_epoch']
                or (metadata.get('delivery_group') or {})!={'key':key,'part':1,'total':1}):
            raise ProductionToolError('Invalid deterministic control receipt.')
        if kind=='opt_out' and explicit_opt_out(inbound.content) and lead.is_opt_out and content==STOP_REPLY:
            return
        if (kind=='handoff' and not lead.is_opt_out and lead.consent_status=='granted' and conversation.is_paused
                and lead.agent_status=='human_control' and content==HANDOFF_REPLY
                and (evidenced_pause_reason(inbound.content) or precheck(inbound.content))):
            return
        raise ProductionToolError('Control reply is no longer authorized.')
    if (metadata.get('engine')!=ENGINE or not agent_run_id or metadata.get('agent_run_id')!=agent_run_id
            or lead.is_opt_out or lead.consent_status!='granted' or conversation.is_paused or lead.agent_status=='human_control'
            or continuity_state(conversation).get('last_inbound_message_id')!=inbound.id):
        raise ProductionToolError('Lead consent, continuity or engine authorization changed.')
    if not active_approved(project.profile):
        raise ProductionToolError('Project approval was withdrawn before send.')
    require_capability(project.profile)
    run=db.query(AgentRun).filter_by(id=agent_run_id,conversation_id=conversation.id).populate_existing().with_for_update().one()
    rmeta=run.input_snapshot or {}
    if (run.graph_version!=LIVE_ENGINE_VERSION or run.mode!='live' or run.event_id!=pin['event_id']
            or run.prompt_configuration_id!=pin.get('policy_version_id') or rmeta.get('sales_engine_pin')!=pin
            or rmeta.get('message_id')!=inbound.id or rmeta.get('continuity_epoch')!=metadata['continuity_epoch']):
        raise ProductionToolError('Run pin changed before provider send.')
    from .resume_batch import verify_resume_batch
    verify_resume_batch(db,scope,conversation,inbound,run=run)
    current=snapshot(db);policy=_policy(db,run.prompt_configuration_id)
    if not current['configuration'].get('enabled') or not current['published_version_id']:
        raise ProductionToolError('Hermes is no longer enabled.')
    group=(metadata.get('delivery_group') or {}).get('key')
    plan=((run.output_snapshot or {}).get('hermes_delivery_plans') or {}).get(group)
    if not plan or plan.get('kind')!=metadata.get('hermes_delivery_kind'):
        raise ProductionToolError('No persisted Hermes delivery plan.')
    verify_plan_part(plan,metadata,content,key)
    from app.modules.sales_agent.sales_policy import policy_context,compliance_action_holds
    from app.modules.sales_agent.commercial_context import confirmed_profile_facts
    if compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile))):
        raise ProductionToolError('Commercial permissions changed before send.')
    if plan['kind']=='reply':
        from .live_coordinator import restore_draft
        turn=restore_draft((run.output_snapshot or {}).get('live_draft'),scope,inbound.id)
        from .multipart_reply import reply_parts
        parts=reply_parts(turn,conversation.channel)
        index=metadata['delivery_group']['part']
        if run.status!='running' or len(parts)!=len(plan['parts']) or content!=parts[index-1]:
            raise ProductionToolError('Provisional reply no longer matches its draft.')
        observations=turn.prepared.result.tool_observations
        used={x['tool'] for x in observations if x.get('status')=='executed'}
        if not used <= (set(policy.enabled_tools)&set(current['configuration'].get('enabled_tools',()))):
            raise ProductionToolError('A tool used by the prepared reply was disabled.')
        return
    if run.status!='completed':
        raise ProductionToolError('Commercial follow-up requires an accepted provisional reply.')
    op=db.query(HermesSalesOperation).filter_by(**scope.__dict__,id=plan.get('operation_id'),inbound_message_id=inbound.id).one_or_none()
    if not op:raise ProductionToolError('Commercial operation receipt missing.')
    if plan['kind']=='booking':
        from .production_tools import _authorize_tool,_utc
        from app.modules.sales_agent.booking_models import SalesBookingOperation
        from app.modules.sales_crm.models import Meeting,MeetingStatus
        _authorize_tool(db,run,'book_onsite_visit')
        result=op.result_json or {};booking=db.get(SalesBookingOperation,result.get('booking_operation_id'))
        meeting=db.get(Meeting,result.get('meeting_id'))
        if (op.operation_type!='book' or op.status!='completed' or not booking or not meeting
                or booking.meeting_id!=meeting.id or any(getattr(booking,k)!=v for k,v in scope.__dict__.items())
                or meeting.lead_id!=scope.lead_id or meeting.project_id!=scope.project_id or meeting.is_demo
                or meeting.status not in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED}):
            raise ProductionToolError('Confirmed reservation changed before notification.')
        saved=booking.snapshot_json or {};context=saved.get('context') or {};option=saved.get('option') or {}
        if (_utc(meeting.meeting_time).isoformat()!=option.get('starts_at')
                or meeting.assigned_sales_user_id!=option.get('sales_user_id')
                or meeting.duration_minutes!=context.get('duration_minutes')
                or meeting.visit_address!=(context.get('location') or {}).get('address')):
            raise ProductionToolError('Booking snapshot changed before confirmation.')
        return
    if plan['kind'] in {'cancel','reschedule'}:
        from .live_changes import TOOLS,verified_change
        from .production_tools import _authorize_tool
        from app.modules.sales_agent.response_policy import render_channel_text
        if plan['kind']!=op.operation_type:
            raise ProductionToolError('Change receipt type mismatch.')
        _authorize_tool(db,run,TOOLS[op.operation_type])
        if content!=render_channel_text(verified_change(db,scope,op),conversation.channel):
            raise ProductionToolError('Change confirmation does not match native receipt.')
        return
    if plan['kind']!='material' or op.operation_type!='material' or op.status!='pending_delivery':
        raise ProductionToolError('Material operation is not awaiting delivery.')
    from .production_tools import _authorize_tool
    from app.modules.projects.models import SalesAssetShare
    from app.modules.sales_agent.material_delivery import validate_shares
    from app.modules.projects.sales_asset_service import approved_for_turn
    _authorize_tool(db,run,'get_unit_media')
    ids=metadata.get('sales_asset_share_ids') or []
    expected={sid for p in plan['parts'] for sid in p['share_ids']}
    if expected!=set((op.result_json or {}).get('share_ids',[])):
        raise ProductionToolError('Issued shares no longer match the operation.')
    approved={a.id for a in approved_for_turn(db,project_id=scope.project_id,company_id=scope.company_id,channel=conversation.channel)}
    shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(ids)).all() if ids else []
    hashes={digest_text(t.rstrip('.,;)')) for t in re.findall(r'/projects/a/([^\s]+)',content)}
    if (len(shares)!=len(ids) or any(s.sales_asset_id not in approved or s.agent_run_id!=run.id or s.channel!=conversation.channel for s in shares)
            or hashes!={s.token_hash for s in shares} or not validate_shares(db,scope,shares,metadata,subset=True)):
        raise ProductionToolError('Material approval or exact binding changed before send.')


def receipts(db, conversation, scope, plan, *, run_id, inbound_id):
    """Return all accepted IDs, None if never attempted, or block/review.

    A durable queued/sending provider ID is polled via the existing webhook
    state, not resubmitted. Partial groups require manual reconciliation.
    """
    from app.modules.sales_agent.models import OutboundMessage,SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    parts=plan['parts']; keys=[part_key(plan['key'],i,len(parts)) for i in range(1,len(parts)+1)]
    outbox=db.query(OutboundMessage).filter(OutboundMessage.idempotency_key.in_(keys)).all()
    if not outbox:return None
    if len(outbox)!=len(keys):raise ProductionToolError('Partial provider delivery group requires review.')
    indexed={o.idempotency_key:o for o in outbox};ids=[];pending=False
    for key in keys:
        out=indexed[key]
        rows=scoped_messages_query(db,conversation).filter_by(direction='outbound',role='assistant',channel=conversation.channel).filter(SalesMessage.metadata_json['outbound_message_id'].as_string()==out.id).all()
        if len(rows)!=1:raise ProductionToolError('Provider outbox has no unique visible message.')
        row=rows[0];meta=row.metadata_json or {}
        if (out.conversation_id!=scope.conversation_id or out.channel!=conversation.channel or out.provider!=conversation.provider
                or out.agent_run_id!=run_id or meta.get('agent_run_id')!=run_id or meta.get('hermes_inbound_message_id')!=inbound_id
                or meta.get('engine')!=(ENGINE if run_id else CONTROL_ENGINE)
                or (run_id and meta.get('hermes_delivery_kind')!=plan.get('kind'))
                or meta.get('lead_id')!=scope.lead_id or meta.get('project_id')!=scope.project_id
                or row.content!=out.content or not out.provider_message_id or row.provider_message_id!=out.provider_message_id):
            raise ProductionToolError('Uncertain or inconsistent provider receipt; no resend.')
        verify_plan_part(plan,meta,row.content,key)
        valid=ACCEPTED|{'queued','sending','scheduled'}
        if row.status not in valid or out.status not in valid:
            raise ProductionToolError('Provider rejected delivery or receipt needs review.')
        if row.status not in ACCEPTED or out.status not in ACCEPTED:pending=True
        ids.append(row.id)
    if pending:raise ReceiptPending('Waiting for existing provider receipt.')
    return ids
