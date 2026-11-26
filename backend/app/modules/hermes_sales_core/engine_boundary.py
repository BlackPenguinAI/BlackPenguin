"""Keep temporary authorizations separate when an opportunity changes engine.

Only invoked under the existing conversation lock on a routed inbound. No
schema change, global conversation sweep, or mutation of historical receipts.
The legacy-only path is untouched until a Hermes lane has owned this scope.
"""
from hashlib import sha256
from datetime import datetime,timezone
from .engine_selection import HERMES, LANGGRAPH, EngineSelectionError

KEY='sales_engine_boundary'


def transition(db, conversation, inbound, pin):
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.models import AgentRun, SalesFollowUpJob
    from app.modules.sales_agent.engine_router import engine_from_run
    raw=getattr(conversation,'continuity_json',None)
    if not isinstance(raw,dict):return False
    value=continuity.state(conversation);previous=value.get(KEY)
    engine=pin['engine']
    if previous is None and engine==LANGGRAPH:return False
    if previous is not None and previous not in {HERMES,LANGGRAPH}:
        raise EngineSelectionError('Unknown previous engine boundary; review required.')
    if previous==engine:return False
    existing=db.query(AgentRun).filter_by(event_id=pin['event_id']).first()
    if existing and previous is not None:
        raise EngineSelectionError('A prior turn cannot cross an intervening engine boundary.')
    # First Hermes event: prior legacy offers are never interpreted as Hermes
    # choices. The preparation boundary also verifies the last actual reply.
    if previous is not None:
        batch=(inbound.metadata_json or {}).get('hermes_resume_batch')
        if batch:
            # The explicit resume already advanced the control epoch and
            # discarded old offers before binding these original inputs.
            if batch.get('epoch')!=value['epoch'] or not value.get('offer_barrier'):
                raise EngineSelectionError('Resume episode does not own the engine transition.')
        else:
            value['epoch']+=1
        value.update(offer_barrier=True,waiting_for_lead=False)
        conversation.continuity_json=value
        # Pending automatic outreach from the old lane must not be interpreted
        # as new work for the new engine. Already dispatched receipts remain.
        for job in db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').all():
            job.status='cancelled';job.processed_at=datetime.now(timezone.utc).replace(tzinfo=None)
        if engine==LANGGRAPH:
            key='engine-boundary:'+sha256(pin['event_id'].encode()).hexdigest()
            continuity.clear_offers(db,conversation,key)
    value[KEY]=engine;conversation.continuity_json=value
    return True


def check_scheduled(conversation,pin,kind):
    raw=getattr(conversation,'continuity_json',None)
    if not isinstance(raw,dict) or raw.get('lead_id')!=conversation.lead_id or raw.get('project_id')!=conversation.project_id:
        return
    previous=raw.get(KEY)
    if kind!='resume' and previous in {HERMES,LANGGRAPH} and previous!=pin['engine']:
        raise EngineSelectionError('Scheduled work belongs to a superseded engine boundary.')
