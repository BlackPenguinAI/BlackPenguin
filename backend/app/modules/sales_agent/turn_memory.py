"""Bounded structured memory and expiring proposals; never mutate a reservation."""
from .execution import now as workflow_now

from datetime import datetime,timezone,timedelta
from .understanding_contract import ChangeProposal,TurnMemory
from .turn_configuration import digest
from .appointment_context import AppointmentReadTool,ACTIVE,utc
from app.modules.sales_crm.models import Meeting
from app.modules.projects.models import Project,ProjectPropertyType,ProjectUnit


def booking_digest(meeting):
    return digest({key:str(getattr(meeting,key)) for key in ('id','project_id','lead_id','meeting_time','duration_minutes',
        'assigned_sales_user_id','status','visit_property_type_id','visit_unit_id','visit_address','visit_location_label')})


def validate_proposal_scope(db,scope,proposal,*,check_target=True):
    meeting=db.query(Meeting).join(Project,Project.id==Meeting.project_id).filter(Meeting.id==proposal.meeting_id,
        Meeting.lead_id==scope.lead_id,Project.company_id==scope.company_id).one_or_none()
    if not meeting:raise PermissionError('Change proposal refers to another lead or Company.')
    if proposal.kind=='cancel' and any((proposal.target_project_id,proposal.target_property_type_id,proposal.target_unit_id,proposal.starts_at)):
        raise ValueError('A cancellation proposal cannot select replacement details.')
    if not check_target:return meeting
    project_id=proposal.target_project_id or meeting.project_id
    project=db.query(Project).filter_by(id=project_id,company_id=scope.company_id).one_or_none()
    if not project:raise PermissionError('Proposed Project is outside this Company.')
    if proposal.target_property_type_id and not db.query(ProjectPropertyType).filter_by(
        id=proposal.target_property_type_id,project_id=project_id,review_status='confirmed').first():
        raise PermissionError('Proposed type is not approved in the target Project.')
    if proposal.target_unit_id and not db.query(ProjectUnit).filter_by(id=proposal.target_unit_id,project_id=project_id).first():
        raise PermissionError('Proposed unit is outside the target Project.')
    if proposal.target_property_type_id or proposal.target_unit_id:
        from .appointment_context import bind_visit
        bind_visit(db,Meeting(project_id=project_id,lead_id=scope.lead_id),company_id=scope.company_id,
                   property_type_id=proposal.target_property_type_id,unit_id=proposal.target_unit_id)
    return meeting


def propose(db,scope,*,expected_revision,event_key,proposal,now=None):
    from .dialogue_store import load,save
    now=utc(now or workflow_now(datetime).replace(tzinfo=timezone.utc))
    proposal=ChangeProposal.model_validate(proposal)
    meeting=validate_proposal_scope(db,scope,proposal,check_target=False)
    from .dialogue_store import check_scope,DialogueConflict
    from .dialogue_models import SalesDialogueEvent
    from .understanding_contract import DialogueState
    check_scope(db,scope)
    prior=scope.query(db,SalesDialogueEvent).filter_by(event_key=event_key).first()
    if prior:
        if prior.payload_json.get('expected_revision')!=expected_revision or (prior.payload_json.get('metadata') or {}).get('proposal')!=proposal.model_dump(mode='json'):
            raise DialogueConflict('Proposal event key was reused with different arguments.')
        return prior.revision,DialogueState.model_validate(prior.state_after)
    validate_proposal_scope(db,scope,proposal)
    if not now<proposal.expires_at<=now+timedelta(minutes=30):raise ValueError('Proposals expire within 30 minutes.')
    if meeting.status not in ACTIVE or booking_digest(meeting)!=proposal.booking_sha256:raise ValueError('Booking changed or is no longer active.')
    if proposal.starts_at and proposal.starts_at<=now:raise ValueError('Replacement time must be in the future.')
    revision,state=load(db,scope)
    if revision!=expected_revision:
        from .dialogue_store import DialogueConflict
        raise DialogueConflict('Dialogue revision changed.')
    previous=next((p for p in state.change_proposals if p.id==proposal.id),None)
    if previous and previous!=proposal:raise ValueError('Proposal identifiers are immutable.')
    if not previous:
        # Pruning expired proposals changes no reservation; previous versions
        # remain available in the append-only event ledger.
        state.change_proposals=[p for p in state.change_proposals if p.expires_at>now][-9:]+[proposal]
    return save(db,scope,event_key=event_key,expected_revision=revision,state=state,
        metadata={'proposal':proposal.model_dump(mode='json'),'reservation_changed':False,'availability_checked':False})


def proposal_context(db,scope,state,*,now):
    result=[]
    for proposal in state.change_proposals:
        try:meeting=validate_proposal_scope(db,scope,proposal)
        except (PermissionError,ValueError):
            result.append({'id':proposal.id,'kind':proposal.kind,'status':'revoked_or_unavailable','authorizes_change':False})
            continue
        status='expired' if proposal.expires_at<=now else 'stale' if booking_digest(meeting)!=proposal.booking_sha256 or meeting.status not in ACTIVE else 'awaiting_explicit_confirmation_and_availability'
        result.append({**proposal.model_dump(mode='json'),'status':status,'authorizes_change':False})
    return result


def remember(state,*,message_id,at,understanding,answered_topics=(),interest=None):
    # No invented prose summary or personality inference. Facts and restrictions
    # have their own authoritative stores; memory points to their turn evidence.
    memory=state.memory
    turns=[r for r in memory.recent_turns if r.get('message_id')!=message_id]
    turns.append({'message_id':message_id,'at':utc(at).isoformat(),
        'requested_topics':[r.topic.value for r in understanding.requests if r.polarity=='request'],
        'declared_fields':[p.key for p in understanding.preferences],
        'selected_property_type_id':interest.get('property_type_id') if interest is not None else state.selected_property_type_id,
        'selected_unit_id':interest.get('unit_id') if interest is not None else state.selected_unit_id})
    turns.sort(key=lambda r:r['at'])
    state.memory=TurnMemory(as_of_message_id=turns[-1]['message_id'],recent_turns=turns[-8:],
        answered_topics=sorted(set(memory.answered_topics)|set(answered_topics),key=str))


def build(db,scope,*,inbound_message_id,now=None):
    from .dialogue_store import check_scope,load
    from .conversation_scope import scoped_messages_query
    from .models import SalesMessage
    from .lead_profile import resolve,for_context
    from .turn_context import latest_outbound
    from app.modules.sales_crm.models import Lead
    now=utc(now or workflow_now(datetime).replace(tzinfo=timezone.utc))
    with db.no_autoflush:
        conversation=check_scope(db,scope)
        inbound=scoped_messages_query(db,conversation).filter_by(id=inbound_message_id,role='user',direction='inbound').one()
        revision,state=load(db,scope)
        history=scoped_messages_query(db,conversation).filter(SalesMessage.id!=inbound.id,SalesMessage.created_at<=inbound.created_at,
            SalesMessage.role.in_(['user','assistant','human'])).order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).limit(20).all()
        pertinent=[];remaining=12000
        for row in history:
            if (row.metadata_json or {}).get('lead_id',scope.lead_id)!=scope.lead_id:continue
            text=row.content[:min(1500,remaining)]
            if not text:break
            pertinent.append({'message_id':row.id,'role':row.role,'content':text,'at':utc(row.created_at).isoformat(),
                              'truncated':len(text)<len(row.content)})
            remaining-=len(text)
        pending=[t.model_dump(mode='json') for t in state.tasks if t.status in {'pending','suspended','blocked','awaiting_user'}]
        tool=AppointmentReadTool(db,scope)
        previous=latest_outbound(db,conversation.id,skip_language_holds=True)
        lead=db.get(Lead,scope.lead_id)
        return {'version':'sales-turn-context/1.0','scope':scope.__dict__,'state_revision':revision,
            'lead_identity':{'first_name':(lead.full_name or '').strip().split()[0] if (lead.full_name or '').strip() else None,'source':'lead_record'},
            'lead_profile':for_context(resolve(lead)),
            'current_interest':{'project_id':scope.project_id,'property_type_id':state.selected_property_type_id,'unit_id':state.selected_unit_id,
                                'source':'dialogue_state','changes_existing_visit':False},
            'appointments':{category:tool.execute({'category':category,'limit':5},now=now) for category in ('active','past','cancelled')},
            'memory':state.memory.model_dump(mode='json'),'history':list(reversed(pertinent)),
            'history_coverage':{'messages':len(pertinent),'bounded':True,'older_messages_omitted':len(history)==20 or remaining<=0},
            'wait_context':state.wait_context,
            'cancellation_search':state.cancellation_search,'cancellation_proposal':state.cancellation_proposal,
            'cancellation_followup_id':state.cancellation_followup_id,
            'reschedule_search':state.reschedule_search,'reschedule_proposal':state.reschedule_proposal,
            'booking_search':state.booking_search,'booking_proposal':state.booking_proposal,
            'cadence':{'status':state.cadence_status,'reason':state.cadence_stop_reason},
            'pending_tasks':pending[-20:],'pending_tasks_truncated':len(pending)>20,
            'constraints':[{**c.model_dump(mode='json'),'evidence':c.evidence[:200],
                            'context_truncated':len(c.evidence)>200} for c in state.constraints],
            'property_constraints':[{**c.model_dump(mode='json'),'evidence':c.evidence[:200]} for c in state.property_constraints],
            'change_proposals':proposal_context(db,scope,state,now=now),
            'qualification_offer':(previous.metadata_json or {}).get('qualification_offer') if previous else None,
            'rule':'Current interest is independent from booked visits. Appointment reads, summaries and proposals never authorize booking, cancellation or rescheduling.'}
