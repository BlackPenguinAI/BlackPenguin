"""The in-app simulator uses the current coordinator with task-local effects."""
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import HTTPException
from .execution import sandbox
from .models import AgentRun, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage
from app.modules.sales_crm.models import Lead


async def turn(db, *, company_id, lead_id, inbound_text, event_id=None,
               record_inbound=True, event_kind='lead_message', follow_up_hours=None,
               virtual_now=None, actor_user_id=None):
    from . import active_service as active, live_service as live
    from .service import get_or_create_conversation, _response
    lead = db.query(Lead).filter_by(id=lead_id, company_id=company_id, deleted_at=None).first()
    if not lead:
        raise HTTPException(404, 'Lead not found.')
    conversation = db.query(SalesConversation).filter_by(lead_id=lead.id, company_id=company_id, channel='simulation').first()
    if not lead.is_demo and not (lead.platform == 'meta' and conversation):
        raise HTTPException(409, 'This endpoint accepts simulation conversations only.')
    conversation = conversation or get_or_create_conversation(db, lead, channel='simulation')
    event_id = event_id or 'simulation:' + str(uuid.uuid4())
    previous = db.query(AgentRun).filter_by(event_id=event_id).first()
    if previous:
        if previous.conversation_id != conversation.id:
            raise HTTPException(409, 'Simulation event belongs to another conversation.')
        if previous.status in {'completed', 'blocked'}:
            return _response(previous, previous.output_snapshot or {})
    if lead.is_opt_out or (conversation.is_paused and conversation.pause_reason != 'Simulation/draft mode'):
        raise HTTPException(409, 'Review and resume the paused conversation before continuing.')
    simulation = db.query(SalesAgentSimulation).filter_by(conversation_id=conversation.id).first()
    clock = virtual_now or (simulation.virtual_now if simulation else datetime.utcnow())
    if clock.tzinfo:
        clock = clock.astimezone(timezone.utc).replace(tzinfo=None)
    latest = db.query(SalesMessage).filter_by(conversation_id=conversation.id).order_by(SalesMessage.created_at.desc()).first()
    if latest and clock <= latest.created_at:
        clock = latest.created_at + timedelta(microseconds=1)
    if simulation:
        simulation.virtual_now = clock
    conversation.is_paused = False
    conversation.pause_reason = None
    db.commit()
    with sandbox(db, conversation, clock):
        if record_inbound:
            inbound = db.query(SalesMessage).filter_by(conversation_id=conversation.id, provider_message_id=event_id, direction='inbound').first()
            if not inbound:
                inbound = SalesMessage(conversation_id=conversation.id, channel='simulation', direction='inbound',
                    role='user', content=inbound_text, status='received', provider_message_id=event_id,
                    created_at=clock, metadata_json={'lead_id':lead.id,'simulation':True})
                db.add(inbound); db.commit()
            await active.maybe_process_active(db, conversation, inbound, event_id_override=event_id)
            run = db.query(AgentRun).filter_by(event_id=event_id).one()
        else:
            run = previous or AgentRun(conversation_id=conversation.id, event_id=event_id, mode='simulation',
                graph_version=active.ENGINE, toolset_version='sales-actions/1.0', model='deterministic/current',
                prompt_snapshot={}, input_snapshot={'event_kind':event_kind})
            if event_kind == 'follow_up':
                if active.active_followup_requires_review(db,conversation):
                    run.status='blocked';run.output_snapshot={'reply':None,'intent':'scheduled_follow_up','proposed_actions':[]};db.add(run);db.commit()
                    return _response(run,run.output_snapshot)
                result = active.active_followup_result(db, conversation)
                reply = result['proposed_reply']
            else:
                from app.modules.projects.models import Project
                project = db.get(Project, conversation.project_id)
                reply = live._initial_message(lead, project, None)
            run.status = 'completed';run.completed_at=clock
            run.output_snapshot={'reply':reply,'intent':event_kind,'proposed_actions':[],
                                 'metadata':{'simulation':True,'workflow_version':'sales-current/1.0'}}
            db.add(run);db.commit()
            await live._dispatch(db,conversation=conversation,lead=lead,content=reply,role='assistant',
                                 agent_run_id=None,metadata={'simulation':True},idempotency_key='simulation:'+run.id)
        from .first_booking import cadence_stopped
        if not conversation.is_paused and not lead.is_opt_out and not cadence_stopped(db,conversation):
            lead.agent_status='simulation'
            live._schedule_next_action(db,conversation,lead,event_id,refresh_pending=True)
        db.commit()
        return _response(run,run.output_snapshot or {})
