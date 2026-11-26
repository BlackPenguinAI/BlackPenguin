"""Durable live turn handoff for an explicitly installed Hermes worker.

No SDK import at module load. No provider is called by this module; the
certified dispatcher owns rendering, consent/policy revalidation at the actual
provider boundary, and the durable outbox. Never infer acceptance from a return
value alone. No automatic fallback or retry of uncertain effects.
"""
from __future__ import annotations
from copy import deepcopy
import json

from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, _hash


def draft_envelope(turn):
    from .staged_runtime import _safe_observations
    prepared=turn.prepared
    data={'scope':dict(prepared.scope.__dict__),'inbound_message_id':prepared.inbound_message_id,
          'expected_revision':prepared.expected_revision,'reply':prepared.result.reply,
          'state':deepcopy(prepared.proposed_state),'menus':deepcopy(turn.proposed_menus),
          'media_offer':deepcopy(turn.presented_media_offer),
          'observations':_safe_observations(prepared.result.tool_observations)}
    if not isinstance(data['reply'],str) or not data['reply'].strip() or len(data['reply'])>4000:
        raise ProductionToolError('Live draft reply exceeds supported bounds.')
    # No arbitrary links from model-generated content. Authorized native
    # materials are emitted only by the opaque share service in live_materials.
    if '/projects/a/' in data['reply']:
        raise ProductionToolError('A model reply cannot contain an asset bearer link.')
    from .bp_state_store import _forbidden_key
    _forbidden_key(data['state']);_forbidden_key(data['menus']);_forbidden_key(data['media_offer'])
    if len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode())>300000:
        raise ProductionToolError('Live draft exceeds supported storage bounds.')
    return {'payload':data,'sha256':_hash(data)}


def restore_draft(envelope,scope,inbound_id):
    """Reconstruct only the exact stored draft. Never rerun the LLM on replay."""
    from .contracts import TurnResult
    from .bp_turn import PreparedHermesTurn
    from .bp_p04_turn import P04PreparedTurn
    if not isinstance(envelope,dict) or not isinstance(envelope.get('payload'),dict):
        raise ProductionToolError('No persisted live draft.')
    data=envelope['payload']
    if (envelope.get('sha256')!=_hash(data) or data.get('scope')!=scope.__dict__
            or data.get('inbound_message_id')!=inbound_id):
        raise ProductionToolError('Stored live draft is inconsistent.')
    return P04PreparedTurn(prepared=PreparedHermesTurn(scope=scope,inbound_message_id=inbound_id,
        expected_revision=data['expected_revision'],result=TurnResult(data['reply'],[],data['observations']),
        proposed_state=deepcopy(data['state'])),proposed_menus=deepcopy(data['menus']),
        presented_media_offer=deepcopy(data['media_offer']))


def persist_live_draft(db,scope,*,inbound_message_id,run_id,turn):
    """Persist the draft before the first provider attempt, caller commits."""
    require_selectable(HERMES)
    from .live_preparation import reserve_live_run
    from .bp_state_store import load
    run=reserve_live_run(db,scope,inbound_message_id=inbound_message_id)
    if run.id!=run_id or run.status!='running':
        raise ProductionToolError('Live run is not eligible for a draft.')
    if turn.prepared.scope!=scope or turn.prepared.inbound_message_id!=inbound_message_id:
        raise ProductionToolError('Live draft scope mismatch.')
    envelope=draft_envelope(turn)
    previous=(run.output_snapshot or {}).get('live_draft')
    if previous:
        if previous!=envelope:raise ProductionToolError('A different live draft was already recorded.')
        return previous
    if run.output_snapshot or load(db,scope).revision!=turn.prepared.expected_revision:
        raise ProductionToolError('Live state changed during preparation.')
    run.output_snapshot={'live_draft':envelope,'reply_ready':True}
    db.flush()
    return envelope


def provisional_delivery_plan(run,scope,inbound_id):
    """Only a stable single-part draft can pass to the shared dispatcher.

    The consumer must independently authorize the send at the actual provider
    boundary, not merely trust this metadata. It must reuse the same outbox
    key, and reconcile existing queued or uncertain sends before any retry.
    """
    require_selectable(HERMES)
    from .production_tools import LIVE_ENGINE_VERSION
    if run.graph_version!=LIVE_ENGINE_VERSION or run.mode!='live' or run.status!='running':
        raise ProductionToolError('Run is not an eligible live draft.')
    turn=restore_draft((run.output_snapshot or {}).get('live_draft'),scope,inbound_id)
    pin=(run.input_snapshot or {}).get('sales_engine_pin') or {}
    if (any(pin.get(k)!=v for k,v in scope.__dict__.items()) or pin.get('engine')!=HERMES
            or pin.get('event_id')!=run.event_id or pin.get('policy_version_id')!=run.prompt_configuration_id
            or (run.input_snapshot or {}).get('message_id')!=inbound_id
            or (run.input_snapshot or {}).get('continuity_epoch') is None):
        raise ProductionToolError('Run pin changed before dispatch.')
    key='hermes:reply:'+run.id
    return {'content':turn.prepared.result.reply,'idempotency_key':key,'metadata':{
        'engine':'hermes-agent','agent_run_id':run.id,'lead_id':scope.lead_id,'project_id':scope.project_id,
        'hermes_inbound_message_id':inbound_id,'continuity_epoch':run.input_snapshot['continuity_epoch'],
        'delivery_group':{'key':key,'part':1,'total':1}}}


def reconcile_live_reply(db,scope,*,inbound_message_id,run_id,outbound_message_id):
    """Commit the accepted reply and state first; commercial effects are later."""
    require_selectable(HERMES)
    from app.modules.sales_agent.models import AgentRun
    from .live_receipts import commit_live_receipt
    run=db.get(AgentRun,run_id)
    if not run:raise ProductionToolError('Missing live run.')
    turn=restore_draft((run.output_snapshot or {}).get('live_draft'),scope,inbound_message_id)
    return commit_live_receipt(db,turn,run_id=run_id,outbound_message_id=outbound_message_id)


def next_native_effect(state,inbound_id):
    """Classify only drafts tied to this inbound, never model success text."""
    material=(state.get('offered_assets') or {}).get('pending_request') or {}
    booking=state.get('confirmation_request') or {}
    prefs=state.get('search_preferences') or {}
    kinds=[]
    if material.get('source_inbound_message_id')==inbound_id:kinds.append('material')
    if booking.get('confirmed_inbound_message_id')==inbound_id and booking.get('status') in {'execution_requested','committed'}:
        kind=booking.get('kind')
        from .live_changes import CHANGE_VERSION
        if kind!='book' and (kind not in {'cancel','reschedule'} or booking.get('live_change_version')!=CHANGE_VERSION):
            raise ProductionToolError('Live change of existing booking is not certified.')
        kinds.append(kind)
    if len(kinds)>1:raise ProductionToolError('Multiple commercial effects require separate turns.')
    return {'kind':kinds[0] if kinds else None,'preferences':prefs.get('last_source_message_id')==inbound_id}


def advance_live_effects(db,scope,*,inbound_message_id):
    """Execute native adapters after durable accepted provisional receipt.

    Caller commits/rolls back separately from the already accepted reply.
    Returned material content is a sensitive internal delivery plan; never
    log/serialize it to UI or treat issuance as provider delivery. Calendar
    synchronization continues through the existing booking outbox worker.
    """
    require_selectable(HERMES)
    from .production_tools import _load_live_turn,persist_live_preferences,execute_first_live_booking
    from .live_materials import issue_live_material_batch
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_message_id)
    selected=next_native_effect(receipt.state_after,inbound.id)
    result={'kind':selected['kind'],'profile':None,'effect':None}
    # Profile write doesn't advance Hermes state. Run it before the native
    # effect which can advance the revision; retries must reconcile receipts.
    if selected['preferences'] and not (run.output_snapshot or {}).get('native_live_profile'):
        result['profile']=persist_live_preferences(db,scope,inbound_message_id=inbound.id)
    if selected['kind']=='book':
        result['effect']=execute_first_live_booking(db,scope,inbound_message_id=inbound.id)
    elif selected['kind'] in {'cancel','reschedule'}:
        from .live_changes import execute_live_change
        operation=execute_live_change(db,scope,inbound_message_id=inbound.id)
        result['effect']={**operation.result_json,'operation_id':operation.id}
    elif selected['kind']=='material':
        result['effect']=issue_live_material_batch(db,scope,inbound_message_id=inbound.id)
    return result
