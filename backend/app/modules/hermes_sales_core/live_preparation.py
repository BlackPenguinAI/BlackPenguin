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

# Live appointment changes are read-only drafts until native receipt authorization.
# Arbitrary CRM updates remain explicitly denied.
LIVE_DRAFT_TOOLS = frozenset({'get_unit_media','select_visit_time','book_onsite_visit','track_property_interest','cancel_onsite_visit','reschedule_onsite_visit'})
BLOCKED = frozenset({'update_lead_profile'})


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
    from .resume_batch import verify_resume_batch
    verify_resume_batch(db,scope,conversation,inbound)
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
    batch=(inbound.metadata_json or {}).get('hermes_resume_batch')
    if run:
        if ((run.input_snapshot or {}).get('hermes_resume_batch')!=batch or run.conversation_id!=conversation.id or run.mode!='live' or run.graph_version!=LIVE_ENGINE_VERSION
                or run.prompt_configuration_id!=pin['policy_version_id'] or (run.input_snapshot or {}).get(PIN_KEY)!=pin
                or (run.input_snapshot or {}).get('message_id')!=inbound.id
                or (run.input_snapshot or {}).get('continuity_epoch')!=epoch(conversation)):
            raise ProductionToolError('Existing run cannot be reassigned or replayed.')
        return run
    run=AgentRun(conversation_id=conversation.id,event_id=event,mode='live',status='running',
        graph_version=LIVE_ENGINE_VERSION,toolset_version='hermes-tools/1.0',model=policy.model,
        prompt_configuration_id=pin['policy_version_id'],prompt_snapshot={'published_version_id':pin['policy_version_id']},
        input_snapshot={'message_id':inbound.id,PIN_KEY:pin,'continuity_epoch':epoch(conversation),'runtime_lane':'live',**({'hermes_resume_batch':deepcopy(batch)} if batch else {})},
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
            self.search_batches=[];self.slot_batches=[];self.comparison_batches=[]
            self.comparison_rows=[];self.comparison_details={};self.primary_captured=False
            self.prepared_visit=None;self.domain_observations=[]
            self.prior_visit_offer=deepcopy(working.get('last_slot_search'))
            self.prior_visit_draft=deepcopy(working.get('visit_draft'))

        def prepare_context(self,context):
            import re
            from .conversation_parity import named_rows,display_name
            super().prepare_context(context)
            # Explicit multi-property reads do not select a single focus.
            named=named_rows(self._all_rows(),self.message)
            if (2<=len(named)<=3 and len({display_name(r).casefold() for r in named})==len(named)
                    and re.search(r'\b(?:compare|comparison|between|difference|which.{0,80}more)\b',self.message,re.I)
                    and not re.search(r'\b(?:send|share|book|visit|cancel|reschedule)\b',self.message,re.I)):
                self.comparison_rows=deepcopy(named)
                context['explicit_comparison_properties']=[{**r,'display_name':display_name(r)} for r in named]

        def _details(self,args):
            from .conversation_parity import display_name
            if self.comparison_rows and args.get('unit_id'):
                row=self._resolve(args['unit_id'])
                if row and row['reference'] in {r['reference'] for r in self.comparison_rows}:
                    result=BlackPenguinReadPort._details(self,args)
                    if result.get('ok'):
                        result['property']['display_name']=display_name(result['property'])
                        self.comparison_details[row['reference']]=deepcopy(result['property'])
                        if set(self.comparison_details)=={r['reference'] for r in self.comparison_rows}:
                            self.comparison_batches.append(list(deepcopy(self.comparison_details).values()))
                    return result
            return super()._details(args)

        def _compare(self,args):
            from .conversation_parity import display_name
            result=super()._compare(args)
            if result.get('ok'):
                for row in result['properties']:
                    row['display_name']=display_name(row)
                self.comparison_batches.append(deepcopy(result['properties']))
            return result

        def _slots(self,args):
            result=super()._slots(args)
            if result.get('ok'):
                self.slot_batches.append({'result':deepcopy(result),'offer':deepcopy(self.state.get('last_slot_search')),
                    'draft':deepcopy(self.state.get('visit_draft')),'args':deepcopy(args)})
            return result

        def invoke(self,name,arguments,scope):
            if scope!=snapshot.scope:raise PermissionError('Live tool scope mismatch.')
            if name in BLOCKED:
                return {'error':'This action requires staff assistance.','error_code':'LIVE_ACTION_NOT_CERTIFIED'}
            # A held commercial topic must not be disclosed by broad catalog tools.
            if holds:
                return {'error':'Approved commercial restrictions require staff review.','error_code':'COMMERCIAL_POLICY_HOLD'}
            try:
                from .commercial_delivery import replay_visit_choice
                resolved=replay_visit_choice(self,name,arguments)
                if resolved is not None:
                    return resolved
                return super().invoke(name,arguments,scope)
            finally:
                # Draft tools only read; release any read/asset lock between calls.
                db.rollback()

        def _search(self,args):
            from .commercial_delivery import strict_search_bounds
            # Hermes may run independent exploratory searches. Do not replace
            # its explicit arguments with the buyer's requested search. The
            # delivery boundary can recover an omitted exact query once.
            args=strict_search_bounds(self.message,args)
            result=super()._search(args)
            if result.get('ok'):
                # Exact, turn-local copies from the authorized port, not the
                # SDK's proposed text. No extra DB writes or retained history.
                self.search_batches.append({'rows':deepcopy(self.search_rows),
                    'search':deepcopy(self.state.get('active_search'))})
            else:
                # Demo parity: the rejected search contributes no facts and
                # remains rejected, but does not erase an earlier valid read.
                from .numbered_catalog import RECOVERABLE_SEARCH_ERRORS
                if (result.get('error_code') in RECOVERABLE_SEARCH_ERRORS
                        and self.search_batches
                        and self.state.get('active_search')==self.search_batches[-1]['search']):
                    self.search_rows=deepcopy(self.search_batches[-1]['rows'])
                    result={**result, 'next_action':(
                        'This search was not executed. Reuse the earlier successful catalog '
                        'result if it answers the buyer; correct the arguments only if needed. '
                        'Do not change primary preferences or repeat an invalid search.')}
            return result

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

        def _media_request(self,args):
            from .conversation_parity import media_tags
            from .live_multi_material import draft_multi_material
            if len(media_tags(self.message))>1:
                return draft_multi_material(self,args)
            return super()._media_request(args)

        def _cancel_request(self,args):
            from .live_changes import draft_change
            return draft_change(self,'cancel',args)

        def _reschedule_request(self,args):
            from .live_changes import draft_change
            return draft_change(self,'reschedule',args)
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
    from .resume_batch import verify_resume_batch
    sources=verify_resume_batch(db,scope,conversation,inbound,run=run)
    if len(sources)>1:
        # The prior genuine messages are already present in chronological
        # scoped history. Ensure no truncation or missing source is hidden.
        expected=[{'role':'user','content':r.content} for r in sources[:-1]]
        if history[-len(expected):]!=expected:
            raise ProductionToolError('The complete pending context is not visible to the SDK.')
    invalidate_stale_choice(working,latest)
    from .scheduled_work import invalidate_boundary
    invalidate_boundary(working,latest,conversation)
    from .live_changes import CHANGE_VERSION, active_visits
    pending_change=working.get('confirmation_request') or {}
    if pending_change.get('live_change_version')==CHANGE_VERSION and pending_change.get('status')=='awaiting_confirmation' and (latest is None or latest.id!=pending_change.get('recap_message_id')):
        working['confirmation_request']=None
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
        'state_revision':loaded.revision,
        'active_visits':active_visits(db,scope,now=datetime.now(timezone.utc)),
        'visit_change_guidance':'Use the active visit ID for cancellation or same-property time replacement. For a change, call the matching tool to produce a recap, never claim success. A later explicit yes may confirm only that exact recap. For replacement request an exact offered date and hour.'})
    if len(sources)>1:
        context['resume_guidance'] = ('The last '+str(len(sources))+' buyer messages are unanswered originals from a resumed conversation. '
            'Address them together. Earlier messages are context, not current authorization. '
            'Do not claim an operation occurred; ask for a fresh explicit instruction when needed.')
    port=_live_port(db,data,working,inbound,holds);port.prepare_context(context)
    # Copy ORM data needed for output validation before releasing locks.
    from types import SimpleNamespace
    project_view=SimpleNamespace(name=project.name,city=project.city)
    lead_view=SimpleNamespace(full_name=lead.full_name,lead_profile_data=deepcopy(lead.lead_profile_data))
    buyer_message=inbound.content; channel=conversation.channel
    db.commit()  # no row lock or open transaction during LLM inference
    from .commercial_delivery import (primary_declaration,primary_ack,search_reply,visit_reply,compare_reply,
        capture_primary,prepare_visit_choice,ensure_search,safe_visit_tools)
    primary_snapshot=None
    if len(sources)==1:
        # Demo begin_turn: capture only explicit self-declarations and resolve
        # only an actually delivered typed visit choice. Native port and policy
        # remain the sole authority; no provider effect can occur here.
        primary_snapshot=capture_primary(port,enabled)
        if ('update_search_preferences' in enabled and primary_declaration(buyer_message,working)
                and primary_snapshot is None):
            raise ProductionToolError('Explicit preference capture requires reconciliation.')
        selected=prepare_visit_choice(port,enabled)
        context.update(primary_preferences=deepcopy(working.get('search_preferences')),
            visit_draft=deepcopy(working.get('visit_draft')),
            last_slot_search=deepcopy(working.get('last_slot_search')),
            confirmation_request=deepcopy(working.get('confirmation_request')))
        if selected:
            context['verified_visit_selection']={'type':selected['kind'],
                'result':selected['result'], 'guidance':('The current selection was already verified by the domain. '
                'Use this result to answer. A selected day needs a time; a selected time is not booking consent. '
                'Do not repeat or replace this choice or claim a visit is booked.')}
    pre_domain_count=len(port.domain_observations)
    result=HermesSalesRuntime(settings,port,state_draft_tools=frozenset({'update_search_preferences'}),
        operational_draft_tools=LIVE_DRAFT_TOOLS,enabled_tools=enabled).process_turn(TurnRequest(
            scope=scope,message=buyer_message,history=history,verified_context=context,channel=channel))
    if primary_snapshot is not None and working.get('search_preferences')!=primary_snapshot:
        raise ProductionToolError('Explicit preference draft changed after inference.')
    # Recover a missing/wrong unambiguous search only through the authorized
    # read port, like demo delivery_policy. Mixed or denied operations stay
    # on the normal path. Finalize against the actual resulting search rows.
    if len(sources)==1:
        ensure_search(port,result.tool_observations,enabled)
    catalog_observations=(port.domain_observations[:pre_domain_count]+result.tool_observations+
                          port.domain_observations[pre_domain_count:])
    reply=port.finalize_reply(result.reply)
    pending=(working.get('offered_assets') or {}).get('pending_request') or {}
    booking=working.get('confirmation_request') or {}
    material_now=pending.get('source_inbound_message_id')==inbound_message_id
    booking_now=booking.get('status')=='execution_requested' and booking.get('confirmed_inbound_message_id')==inbound_message_id
    canonical_search_reply=False
    if material_now and booking_now:
        raise ProductionToolError('Concurrent commercial effects need separate turns.')
    if material_now:reply='I found the requested material. I still need to validate the share before sending it.'
    elif booking_now:
        reply={'cancel':'I will check your cancellation. Your visit is not cancelled yet.',
               'reschedule':'I will check the replacement. Your original visit is unchanged for now.'}.get(booking.get('kind'),'I will check whether your selected visit can be confirmed. It is not booked yet.')
    elif booking.get('live_change_version')==CHANGE_VERSION and booking.get('status')=='recap_required' and booking.get('selected_inbound_message_id')==inbound_message_id:
        from .live_changes import change_recap
        reply=change_recap(booking)
    elif len(sources)==1:
        if port.prepared_visit and not safe_visit_tools(port,result.tool_observations):
            raise ProductionToolError('Verified visit selection requires reconciliation.')
        # Domain-owned verified delivery contracts, as in demo v13.3.3.
        # Never re-run an external action or replace Hermes's inference loop.
        commercial_reply=visit_reply(port,result.tool_observations,enabled)
        if commercial_reply is None:
            commercial_reply=compare_reply(port,result.tool_observations)
        if commercial_reply is None:
            commercial_reply=search_reply(port,result.tool_observations,channel,model_reply=reply)
            canonical_search_reply=commercial_reply is not None
        # A simple explicit declaration is a state update, not a required
        # search. Keep the natural answer when it is already grounded; the
        # monetary fallback below can acknowledge the verified declaration.
        if commercial_reply is not None:
            reply=commercial_reply
    from app.modules.sales_agent.response_policy import render_channel_text,split_channel_text
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    from app.modules.sales_agent.language_policy import detect,scoped_names
    reply=render_channel_text(reply,channel)
    # Use the same persisted-profile monetary evidence as live_service._dispatch.
    # A canonical search reply must not depend on a preparation-only exemption.
    checked,evidence=validate_monetary_reply(reply,data.commercial,lead_profile=lead_view.lead_profile_data)
    from .numbered_catalog import reconcile_direct_catalog
    # A direct, exact catalog-list request is a structured presentation
    # contract even if the model happened to quote valid prices. Preserve its
    # order when proven, and avoid letting a speculative search change the
    # membership of the new menu. Non-eligible turns keep the ordinary path.
    direct_repair = None
    if not (material_now or booking_now or len(sources)>1 or canonical_search_reply) and port.search_batches:
        direct_repair=reconcile_direct_catalog(reply,buyer_message=buyer_message,
            search_batches=port.search_batches,menus=port.menus,observations=catalog_observations,
            active_search=working.get('active_search'),inbound_id=inbound_message_id,
            media_offer=port.offered_media,channel=channel)
    if direct_repair is not None:
        candidate,menu,selected_search=direct_repair
        checked,evidence=validate_monetary_reply(candidate,data.commercial,lead_profile=lead_view.lead_profile_data)
        if checked!=candidate or not evidence.get('checked') or evidence.get('replaced'):
            raise ProductionToolError('Reply requires monetary reconciliation before dispatch.')
        reply=candidate
        port.menus=[menu]
        working['active_search']=deepcopy(selected_search)
        # The accepted reply receipt will establish the actual menu and
        # last_presented_units, not any speculative later search.
        working['last_presented_units']=[]
    elif checked!=reply or evidence.get('replaced'):
        # A rejected model-rendered price must never be dispatched. For a pure,
        # already verified numbered catalog search, reconstruct the displayed
        # subset/order from this turn's actual search result. Re-run the exact
        # same guard; do not accept its generic fallback or new LLM inference.
        from .numbered_catalog import reconcile_catalog_delivery
        repair = None if material_now or booking_now or len(sources)>1 else reconcile_catalog_delivery(
            reply,buyer_message=buyer_message,search_batches=port.search_batches,menus=port.menus,
            observations=catalog_observations,active_search=working.get('active_search'),
            inbound_id=inbound_message_id,media_offer=port.offered_media,channel=channel)
        if repair is not None:
            candidate,menu=repair
            checked,evidence=validate_monetary_reply(candidate,data.commercial,lead_profile=lead_view.lead_profile_data)
            if checked!=candidate or not evidence.get('checked') or evidence.get('replaced'):
                raise ProductionToolError('Reply requires monetary reconciliation before dispatch.')
            reply=candidate
            port.menus=[menu]
        else:
            candidate=None
            if not (material_now or booking_now or len(sources)>1):
                candidate=search_reply(port,result.tool_observations,channel,monetary_rejected=True)
                if candidate is None:
                    candidate=primary_ack(port,result.tool_observations)
            if candidate is None:
                raise ProductionToolError('Reply requires monetary reconciliation before dispatch.')
            candidate=render_channel_text(candidate,channel)
            # A newly declared preference is persisted after delivery. Do not
            # manufacture an earlier CRM write to make this reply pass.
            checked,evidence=validate_monetary_reply(candidate,data.commercial,lead_profile=lead_view.lead_profile_data)
            if checked!=candidate or evidence.get('replaced'):
                raise ProductionToolError('Reply requires monetary reconciliation before dispatch.')
            reply=candidate
    if detect(reply,names=scoped_names(project_view,lead_view,data.commercial),output=True).needs_reentry:
        raise ProductionToolError('Reply requires language reconciliation before dispatch.')
    working.pop('_active_source_message_id',None)
    # Persist actual domain calls as well as SDK calls. No invented execution;
    # the evaluator distinguishes pre/post-domain calls from SDK traces.
    result=replace(result,tool_observations=(port.domain_observations[:pre_domain_count]+result.tool_observations+
                                            port.domain_observations[pre_domain_count:])[-50:])
    turn=P04PreparedTurn(prepared=PreparedHermesTurn(scope=scope,inbound_message_id=inbound_message_id,
        expected_revision=loaded.revision,result=replace(result,reply=reply),proposed_state=working),
        proposed_menus=deepcopy(port.menus),presented_media_offer=deepcopy(port.offered_media))
    from .multipart_reply import reply_parts
    reply_parts(turn,channel)
    return turn
