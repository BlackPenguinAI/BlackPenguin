"""HEI-03B continuation: bind live Hermes drafts to actual accepted outbox rows.

No model or provider calls here. No synthetic SalesMessage or provider IDs.
Caller owns the transaction. The production readiness gate is still required.
Single-part replies only; uncertain or altered responses require reconciliation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .engine_selection import HERMES, require_selectable
from .production_tools import LIVE_ENGINE_VERSION, LIVE_RECEIPT_PREFIX, ProductionToolError


def validate_binding(scope, inbound, run, pin, row, out):
    """Pure structural proof; caller independently loads scoped provider rows."""
    meta = row.metadata_json or {}
    imeta = inbound.metadata_json or {}
    rmeta = run.input_snapshot or {}
    expected = {**scope.__dict__, 'event_id':run.event_id, 'engine':HERMES,
                'policy_version_id':run.prompt_configuration_id}
    if (not run.prompt_configuration_id or pin != expected or imeta.get('sales_engine_pin') != pin
            or rmeta.get('sales_engine_pin') != pin or rmeta.get('message_id') != inbound.id
            or rmeta.get('continuity_epoch') is None or run.conversation_id != scope.conversation_id
            or run.graph_version != LIVE_ENGINE_VERSION or run.mode != 'live'
            or run.status not in {'running','completed'}):
        raise ProductionToolError('Live receipt requires the exact pinned Hermes run.')
    if (inbound.conversation_id != scope.conversation_id or inbound.direction != 'inbound'
            or inbound.role != 'user' or not inbound.provider_message_id
            or imeta.get('lead_id') != scope.lead_id or imeta.get('project_id') != scope.project_id
            or row.channel != inbound.channel or row.channel not in {'sms','whatsapp'}
            or meta.get('hermes_inbound_message_id') != inbound.id
            or meta.get('engine') != 'hermes-agent' or meta.get('agent_run_id') != run.id
            or out.agent_run_id != run.id or (row.created_at,row.id) <= (inbound.created_at,inbound.id)):
        raise ProductionToolError('The accepted reply is not attributable to this inbound.')
    group = meta.get('delivery_group') or {}
    if group.get('total') != 1 or group.get('part') != 1 or not group.get('key'):
        raise ProductionToolError('Live state requires a complete single-part delivery.')
    if out.idempotency_key != group['key']:
        raise ProductionToolError('Delivery group does not match the outbox key.')


def state_for_accepted_reply(turn, row):
    """Only actual visible text can create a menu or actionable confirmation."""
    from .bp_operation_receipts import recap_visible, visible_menu
    from .choice_state import record_delivered_menu
    from .conversation_parity import commit_property_menu
    prepared = turn.prepared
    if row.content != prepared.result.reply:
        raise ProductionToolError('Actual reply differs from the prepared text; review before saving.')
    state = deepcopy(prepared.proposed_state)
    state['last_presented_choice_set'] = None
    state['choice_set_initialized'] = True
    offered = state.get('last_slot_search') or {}
    if offered.get('source_inbound_message_id') == prepared.inbound_message_id:
        # Do not authorize a hidden result, including a single slot without
        # the current production offer contract's visible evidence.
        offered['source_reply_message_id'] = None
        for menu in reversed(turn.proposed_menus):
            if (menu.get('type') in {'visit_day','visit_time'}
                    and menu.get('unit_id') == offered.get('unit_id')
                    and menu.get('proposal_id') in (None,offered.get('proposal_id'))
                    and visible_menu(row.content,menu)):
                state['last_presented_choice_set'] = record_delivered_menu(state,menu=menu,outbound_message_id=row.id)
                offered['source_reply_message_id'] = row.id
                break
    if state['last_presented_choice_set'] is None:
        commit_property_menu(state,turn.proposed_menus,row.content,row.id)
    offers = state.setdefault('offered_assets',{})
    offers.pop('presented_offer',None)
    if turn.presented_media_offer:
        offers['presented_offer'] = {**turn.presented_media_offer,'source_reply_message_id':row.id}
    proposal = state.get('confirmation_request') or {}
    if (proposal.get('kind') == 'book' and proposal.get('status') == 'recap_required'
            and proposal.get('selected_inbound_message_id') == prepared.inbound_message_id):
        address = proposal.get('visit_address')
        zone = proposal.get('timezone')
        if (isinstance(address,str) and address.strip() and isinstance(zone,str) and zone.strip()
                and address.casefold() in row.content.casefold() and zone.casefold() in row.content.casefold()
                and recap_visible(row.content,proposal)):
            proposal['status'] = 'awaiting_confirmation'
            proposal['recap_message_id'] = row.id
    from .live_changes import recap_matches
    if (proposal.get('status')=='recap_required' and proposal.get('selected_inbound_message_id')==prepared.inbound_message_id
            and recap_matches(row.content,proposal)):
        proposal['status']='awaiting_confirmation'
        proposal['recap_message_id']=row.id
    state['last_assistant_reply'] = row.content
    return state


def commit_live_receipt(db, turn, *, run_id: str, outbound_message_id: str):
    """Reconcile real delivery and save state/AgentRun together, never send again."""
    require_selectable(HERMES)
    from app.modules.sales_agent.models import SalesConversation, SalesMessage, AgentRun
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.continuity import check_epoch
    from app.modules.sales_crm.models import Lead
    from .bp_context import require_scoped_entities
    from .bp_models import HermesSalesStateEvent
    from .bp_state_store import load, save
    from .production_tools import _verify_provider_receipt, _hash
    from .staged_runtime import _safe_observations
    prepared = turn.prepared
    scope = prepared.scope
    conversation = db.query(SalesConversation).filter_by(id=scope.conversation_id,
        company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id
        ).populate_existing().with_for_update().one()
    db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,project_id=scope.project_id
        ).populate_existing().with_for_update().one()
    _,project,lead,conversation = require_scoped_entities(db,scope)
    if (conversation.channel not in {'sms','whatsapp'} or lead.is_demo or lead.deleted_at
            or lead.is_opt_out or lead.consent_status != 'granted' or conversation.is_paused
            or lead.agent_status == 'human_control'):
        raise ProductionToolError('Live opportunity is not authorized for receipt reconciliation.')
    from app.modules.onboarding_versions import require_capability
    require_capability(project.profile)
    q = scoped_messages_query(db,conversation)
    inbound = q.filter_by(id=prepared.inbound_message_id,direction='inbound',role='user').one()
    row = q.filter_by(id=outbound_message_id).one()
    run = db.query(AgentRun).filter_by(id=run_id,conversation_id=conversation.id).populate_existing().with_for_update().one()
    pin = (inbound.metadata_json or {}).get('sales_engine_pin')
    out = _verify_provider_receipt(db,row,scope,conversation.channel)
    validate_binding(scope,inbound,run,pin,row,out)
    check_epoch(conversation,run.input_snapshot['continuity_epoch'])
    from .live_coordinator import draft_envelope
    if (run.output_snapshot or {}).get('live_draft') != draft_envelope(turn):
        raise ProductionToolError('Receipt must match the immutable prepared draft.')
    state = state_for_accepted_reply(turn,row)
    key = LIVE_RECEIPT_PREFIX+inbound.id
    prior = db.query(HermesSalesStateEvent).filter_by(**scope.__dict__,event_key=key).one_or_none()
    if prior:
        meta = (run.output_snapshot or {}).get('metadata') or {}
        if (run.status!='completed' or meta.get('message_id')!=row.id or meta.get('state_revision')!=prior.revision
                or prior.event_type!='outbound_choice_receipt' or prior.state_after!=state
                or prior.payload_hash!=_hash(state)):
            raise ProductionToolError('Existing live state receipt is inconsistent.')
        return {'run_id':run.id,'message_id':row.id,'state_revision':prior.revision,'replayed':True}
    if run.status!='running' or load(db,scope).revision!=prepared.expected_revision:
        raise ProductionToolError('A newer revision or completed run supersedes the draft.')
    # Do not attach a hidden offer to a message that was superseded by another
    # accepted assistant response. Inbound FIFO handling is separate.
    newer = q.filter(SalesMessage.direction=='outbound',SalesMessage.id!=row.id,
        SalesMessage.created_at>=row.created_at).all()
    if any((m.created_at,m.id)>(row.created_at,row.id) and m.status in {'sent','accepted','delivered','read'} for m in newer):
        raise ProductionToolError('A newer response supersedes this receipt.')
    committed = save(db,scope,expected_revision=prepared.expected_revision,event_key=key,
        state=state,event_type='outbound_choice_receipt')
    run.output_snapshot = {**(run.output_snapshot or {}),'reply':row.content,
        'metadata':{'engine':'hermes','runtime_lane':'live','message_id':row.id,
                    'state_revision':committed.revision,'delivery':'provider_accepted'},
        'tool_observations':_safe_observations(prepared.result.tool_observations)}
    run.status='completed';run.error_code=None;run.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    return {'run_id':run.id,'message_id':row.id,'state_revision':committed.revision,'replayed':False}
