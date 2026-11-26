"""Exact informational multipart replies, no synthetic provider receipts.

Commercial recap/offer/effect or permanent preference mutations remain
single-message until their complete evidence contracts support groups.
"""
from __future__ import annotations
from .production_tools import ProductionToolError


def reply_parts(turn, channel):
    from app.modules.sales_agent.response_policy import render_channel_text,split_channel_text
    prepared=turn.prepared;text=prepared.result.reply
    parts=split_channel_text(text,channel)
    limit=1400 if channel=='sms' else 3500
    if not parts or len(parts)>4 or len(text)>4000 or any(len(p)>limit for p in parts) or render_channel_text(text,channel)!=text:
        raise ProductionToolError('Reply exceeds the supported exact delivery bounds.')
    if len(parts)>1:
        state=prepared.proposed_state; inbound=prepared.inbound_message_id
        request=state.get('confirmation_request') or {}; offered=state.get('last_slot_search') or {}
        material=(state.get('offered_assets') or {}).get('pending_request') or {}
        preferences=state.get('search_preferences') or {}
        if (turn.proposed_menus or turn.presented_media_offer or offered.get('source_inbound_message_id')==inbound
                or material.get('source_inbound_message_id')==inbound or preferences.get('last_source_message_id')==inbound
                or request.get('selected_inbound_message_id')==inbound or request.get('confirmed_inbound_message_id')==inbound):
            raise ProductionToolError('An actionable reply must fit one exact provider message.')
    return parts


def state_for_group(turn):
    from copy import deepcopy
    state=deepcopy(turn.prepared.proposed_state)
    # Never infer a selectable offer from split text. Old temporary approvals
    # are invalidated; durable bookings/preferences remain untouched.
    state.update(last_presented_choice_set=None,choice_set_initialized=True,last_presented_units=[],
                 last_slot_search=None,booking_proposal=None,confirmation_request=None,offered_assets={},
                 last_assistant_reply=turn.prepared.result.reply)
    draft=state.get('visit_draft') or {}
    if draft.get('status') not in {'confirmed','cancelled','rescheduled','committed'}:
        state['visit_draft']={'unit_id':None,'date':None,'start_time':None,'status':'idle'}
    return state


def verified_group(db, scope, conversation, inbound, run, turn, last_id):
    """Every accepted provider part must match its immutable draft and plan."""
    from .provider_delivery import receipts,build_plan
    from .live_receipts import validate_binding
    from .production_tools import _verify_provider_receipt
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    parts=reply_parts(turn,conversation.channel)
    if len(parts)<2:raise ProductionToolError('Expected a multipart draft.')
    key='hermes:reply:'+run.id
    _,expected=build_plan(key,'reply',turn.prepared.result.reply,conversation.channel)
    plan=((run.output_snapshot or {}).get('hermes_delivery_plans') or {}).get(key)
    if plan!=expected:raise ProductionToolError('Reply plan does not match the immutable draft.')
    ids=receipts(db,conversation,scope,plan,run_id=run.id,inbound_id=inbound.id)
    if not ids or len(ids)!=len(parts) or ids[-1]!=last_id:
        raise ProductionToolError('Complete multipart receipt required.')
    q=scoped_messages_query(db,conversation);previous=None
    for i,(identifier,part) in enumerate(zip(ids,parts),1):
        row=q.filter_by(id=identifier).one();out=_verify_provider_receipt(db,row,scope,conversation.channel)
        validate_binding(scope,inbound,run,(inbound.metadata_json or {}).get('sales_engine_pin'),row,out,group=(key,i,len(parts)))
        if row.content!=part or (previous is not None and (row.created_at,row.id)<=previous):
            raise ProductionToolError('Multipart reply order or text changed.')
        previous=(row.created_at,row.id)
    return ids
