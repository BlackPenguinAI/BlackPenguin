"""HEI-03B live Hermes preparation candidate, without provider or CRM writes.

Uses the actual channel, published scope, current tool policy and HEI-02 parity.
P04's simulation entrypoint remains unchanged. Live access stays behind the
hard production gate. This module is called by a certified worker only.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import os

from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, LIVE_ENGINE_VERSION

# Cancellation/rescheduling and arbitrary CRM updates remain explicitly denied
# until their production executors and consent contracts are implemented.
LIVE_DRAFT_TOOLS = frozenset({'get_unit_media','select_visit_time','book_onsite_visit','track_property_interest'})
BLOCKED = frozenset({'cancel_onsite_visit','reschedule_onsite_visit','update_lead_profile'})


def _live_scope(db,scope,inbound_id):
    require_selectable(HERMES)
    from .bp_context import require_scoped_entities
    from app.modules.sales_agent.models import SalesConversation,SalesMessage
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.onboarding_versions import require_capability
    from app.modules.sales_agent.provider_routes import assert_dispatchable
    from app.modules.sales_agent.continuity_policy import explicit_opt_out,evidenced_pause_reason
    from app.modules.sales_agent.moderation import precheck
    from app.modules.sales_agent.continuity import state as continuity_state
    conversation=db.query(SalesConversation).filter_by(id=scope.conversation_id,
        company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id
        ).populate_existing().with_for_update().one()
    db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,project_id=scope.project_id
        ).populate_existing().with_for_update().one()
    _,project,lead,conversation=require_scoped_entities(db,scope)
    if (conversation.channel not in {'sms','whatsapp'} or lead.is_demo or project.is_demo or lead.deleted_at
            or lead.is_opt_out or lead.consent_status!='granted' or conversation.is_paused
            or lead.agent_status=='human_control'):
        raise ProductionToolError('Live conversation is not authorized.')
    require_capability(project.profile)
    assert_dispatchable(db,conversation)
    inbound=scoped_messages_query(db,conversation).filter_by(id=inbound_id,channel=conversation.channel,
        direction='inbound',role='user').one()
    meta=inbound.metadata_json or {}
    if (not inbound.provider_message_id or meta.get('lead_id')!=scope.lead_id
            or meta.get('project_id')!=scope.project_id or meta.get('awaiting_resume')
            or meta.get('resume_context') or not meta.get('continuity_recorded')
            or continuity_state(conversation).get('last_inbound_message_id')!=inbound.id):
        raise ProductionToolError('Current authenticated inbound evidence is required.')
    # Do not send controls into a generative lane. A shared deterministic
    # opt-out / escalation path must be wired before production activation.
    if explicit_opt_out(inbound.content) or evidenced_pause_reason(inbound.content) or precheck(inbound.content):
        raise ProductionToolError('Deterministic control handling required before inference.')
    return project,lead,conversation,inbound


def reserve_live_run(db,scope,*,inbound_message_id):
    """Reserve the existing router pin before inference. Caller commits."""
    require_selectable(HERMES)
    from .staged_runtime import _policy
    from .staff_config import snapshot
    from app.modules.sales_agent.engine_router import event_scope,PIN_KEY
    from app.modules.sales_agent.models import AgentRun
    from app.modules.sales_agent.continuity import epoch
    project,lead,conversation,inbound=_live_scope(db,scope,inbound_message_id)
    pin=(inbound.metadata_json or {}).get(PIN_KEY)
    event=f'{conversation.provider}:{inbound.provider_message_id}'
    if (not isinstance(pin,dict) or any(pin.get(k)!=v for k,v in event_scope(conversation,event).items())
            or pin.get('engine')!=HERMES or not pin.get('policy_version_id')):
        raise ProductionToolError('The router must pin the Hermes event first.')
    current=snapshot(db)
    if not current['configuration'].get('enabled') or not current['published_version_id']:
        raise ProductionToolError('Hermes configuration is disabled.')
    policy=_policy(db,pin['policy_version_id'])
    run=db.query(AgentRun).filter_by(event_id=event).populate_existing().with_for_update().one_or_none()
    if run:
        if (run.conversation_id!=conversation.id or run.mode!='live' or run.graph_version!=LIVE_ENGINE_VERSION
                or run.prompt_configuration_id!=pin['policy_version_id'] or (run.input_snapshot or {}).get(PIN_KEY)!=pin
                or (run.input_snapshot or {}).get('message_id')!=inbound.id
                or (run.input_snapshot or {}).get('continuity_epoch')!=epoch(conversation)):
            raise ProductionToolError('Existing run cannot be reassigned or replayed.')
        return run
    run=AgentRun(conversation_id=conversation.id,event_id=event,mode='live',status='running',
        graph_version=LIVE_ENGINE_VERSION,toolset_version='hermes-tools/1.0',model=policy.model,
        prompt_configuration_id=pin['policy_version_id'],prompt_snapshot={'published_version_id':pin['policy_version_id']},
        input_snapshot={'message_id':inbound.id,PIN_KEY:pin,'continuity_epoch':epoch(conversation),'runtime_lane':'live'},
        output_snapshot={})
    db.add(run);db.flush()
    return run


def _live_port(db,snapshot,working,inbound,holds):
    from .conversation_parity import ParityOperationalPort
    from types import SimpleNamespace
    inbound = SimpleNamespace(id=inbound.id, content=inbound.content)
    from .bp_read_port import BlackPenguinReadPort
    from .production_tools import _material_batch
    from app.modules.projects.locations import resolve_visit_location
    from .bp_context import require_scoped_entities
    # Only this explicit live draft adapter initializes the shared read base.
    # Never forge a simulation channel or remove P04's simulation guard.
    class LiveDraftPort(ParityOperationalPort):
        def __init__(self):
            BlackPenguinReadPort.__init__(self,snapshot,state=working,buyer_message=inbound.content,
                                           enable_preference_drafts=True)
            self.db=db;self.inbound_id=inbound.id;self.now=datetime.now(timezone.utc)
            self.menus=[];self._availability_search=None;self._meeting_reader=None;self._material_reader=None
            self.search_rows=None;self.choice=None;self.explicit_focus=None;self.discovered={};self.offered_media=None

        def invoke(self,name,arguments,scope):
            if scope!=snapshot.scope:raise PermissionError('Live tool scope mismatch.')
            if name in BLOCKED:
                return {'error':'This action requires staff assistance.','error_code':'LIVE_ACTION_NOT_CERTIFIED'}
            # A held commercial topic must not be disclosed by broad catalog tools.
            if holds:
                return {'error':'Approved commercial restrictions require staff review.','error_code':'COMMERCIAL_POLICY_HOLD'}
            try:
                return super().invoke(name,arguments,scope)
            finally:
                # Draft tools only read; release any read/asset lock between calls.
                db.rollback()

        def _verified_material(self,asset_id,row,requested_tag):
            # Actual channel + exact coverage, no SMS assumption for WhatsApp.
            from datetime import timedelta
            try:
                _,project,_,_=require_scoped_entities(db,snapshot.scope)
                _material_batch(db,snapshot.scope,project,snapshot.channel,{
                    'asset_ids':[asset_id],'subject':requested_tag,'unit_id':row['reference'],
                    'expires_at':(self.now+timedelta(minutes=1)).isoformat()},self.now)
                return True
            except (ProductionToolError,ValueError,OSError):
                return False

        def _select_time(self,args):
            _,project,_,_=require_scoped_entities(db,snapshot.scope)
            location=resolve_visit_location(project)
            if not location or not location.get('address'):
                return {'error':'The approved visit location needs staff confirmation.','error_code':'VISIT_LOCATION_REQUIRED'}
            outcome=super()._select_time(args)
            if outcome.get('ok'):
                self.state['confirmation_request']['visit_address']=location['address']
                outcome['selected']['visit_address']=location['address']
                outcome['next_action']='Ask for explicit confirmation of exact property reference, date, HH:MM, timezone and visit address.'
            return outcome

        def _active_meeting(self,meeting_id):
            # Cancel/reschedule are disabled in this live candidate. Never
            # query a demo appointment for a production opportunity.
            return None
    return LiveDraftPort()


def prepare_live_turn(db,scope,*,inbound_message_id,run_id):
    """Real SDK preparation using current approved catalog; no external effects.

    Requires a reserved live run and current policy. No second model. The
    caller owns transaction lifetime and must release it before dispatch.
    """
    require_selectable(HERMES)
    from .bp_context import build_bp_snapshot
    from .bp_state_store import load
    from .bp_turn import PreparedHermesTurn
    from .bp_p04_turn import P04PreparedTurn
    from .conversation_parity import scoped_dialogue,invalidate_stale_choice
    from .config import HermesSettings
    from .contracts import TurnRequest
    from .runtime import HermesSalesRuntime
    from .staff_config import snapshot as staff_snapshot
    from .staged_runtime import _policy
    from app.modules.sales_agent.models import AgentRun
    from app.modules.sales_agent.sales_policy import policy_context,compliance_action_holds
    from app.modules.sales_agent.commercial_context import confirmed_profile_facts
    from app.modules.sales_agent.continuity import check_epoch
    project,lead,conversation,inbound=_live_scope(db,scope,inbound_message_id)
    run=reserve_live_run(db,scope,inbound_message_id=inbound_message_id)
    if run.id!=run_id or run.status!='running' or run.output_snapshot:
        raise ProductionToolError('Existing live draft or receipt must be reconciled without model replay.')
    check_epoch(conversation,run.input_snapshot['continuity_epoch'])
    current=staff_snapshot(db)['configuration'];policy=_policy(db,run.prompt_configuration_id)
    enabled=(frozenset(policy.enabled_tools)&frozenset(current.get('enabled_tools',())))-BLOCKED
    settings=HermesSettings(api_key=os.environ.get('OPENROUTER_API_KEY',''),model=policy.model,
                           max_iterations=policy.max_iterations,prompt=policy.system_prompt)
    data=build_bp_snapshot(db,scope,channel=conversation.channel)
    loaded=load(db,scope);working=deepcopy(loaded.data)
    history,latest=scoped_dialogue(db,scope,conversation,inbound)
    invalidate_stale_choice(working,latest)
    working['_active_source_message_id']=inbound.id
    holds=compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile)))
    if holds:
        # No approved project facts or tool output should reach the model
        # while a held commercial policy requires human review.
        raise ProductionToolError('Commercial action policy requires review before live preparation.')
    context=data.for_hermes();context.update({
        'primary_preferences':deepcopy(working.get('search_preferences')),
        'property_filters':deepcopy(working.get('property_filters')),
        'visit_draft':deepcopy(working.get('visit_draft')),
        'last_slot_search':deepcopy(working.get('last_slot_search')),
        'confirmation_request':deepcopy(working.get('confirmation_request')),
        'state_revision':loaded.revision})
    port=_live_port(db,data,working,inbound,holds);port.prepare_context(context)
    # Copy ORM data needed for output validation before releasing locks.
    from types import SimpleNamespace
    project_view=SimpleNamespace(name=project.name,city=project.city)
    lead_view=SimpleNamespace(full_name=lead.full_name,lead_profile_data=deepcopy(lead.lead_profile_data))
    buyer_message=inbound.content; channel=conversation.channel
    db.commit()  # no row lock or open transaction during LLM inference
    result=HermesSalesRuntime(settings,port,state_draft_tools=frozenset({'update_search_preferences'}),
        operational_draft_tools=LIVE_DRAFT_TOOLS,enabled_tools=enabled).process_turn(TurnRequest(
            scope=scope,message=buyer_message,history=history,verified_context=context,channel=channel))
    reply=port.finalize_reply(result.reply)
    pending=(working.get('offered_assets') or {}).get('pending_request') or {}
    booking=working.get('confirmation_request') or {}
    material_now=pending.get('source_inbound_message_id')==inbound_message_id
    booking_now=booking.get('status')=='execution_requested' and booking.get('confirmed_inbound_message_id')==inbound_message_id
    if material_now and booking_now:
        raise ProductionToolError('Concurrent commercial effects need separate turns.')
    if material_now:reply='I found the requested material. I still need to validate the share before sending it.'
    elif booking_now:reply='I will check whether your selected visit can be confirmed. It is not booked yet.'
    from app.modules.sales_agent.response_policy import render_channel_text,split_channel_text
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    from app.modules.sales_agent.language_policy import detect,scoped_names
    reply=render_channel_text(reply,channel)
    checked,evidence=validate_monetary_reply(reply,data.commercial,lead_profile=lead_view.lead_profile_data)
    if checked!=reply or evidence.get('replaced'):
        raise ProductionToolError('Reply requires monetary reconciliation before dispatch.')
    if detect(reply,names=scoped_names(project_view,lead_view,data.commercial),output=True).needs_reentry:
        raise ProductionToolError('Reply requires language reconciliation before dispatch.')
    if split_channel_text(reply,channel)!=[reply]:
        raise ProductionToolError('Provisional live reply must fit a single unchanged message.')
    working.pop('_active_source_message_id',None)
    return P04PreparedTurn(prepared=PreparedHermesTurn(scope=scope,inbound_message_id=inbound_message_id,
        expected_revision=loaded.revision,result=replace(result,reply=reply),proposed_state=working),
        proposed_menus=deepcopy(port.menus),presented_media_offer=deepcopy(port.offered_media))
