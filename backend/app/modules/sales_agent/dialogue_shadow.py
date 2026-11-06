"""Selective shadow bridge. Legacy output and delivery remain authoritative."""
import logging
import asyncio
from dataclasses import asdict
from app.core.config import settings
from app.modules.ai_core.models import AIConfiguration
from .runtime_policy import RuntimePolicy
from .dialogue_store import Scope, load, save
from .dialogue_models import SalesDialogueEvent
from .understanding_service import preview
from .dialogue_orchestrator import run_turn
from .dialogue_composer import compose
from .understanding_contract import Offer
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from datetime import datetime, timezone, timedelta


def recorded_offers(db,conversation):
    """Only the latest outbound can expose an unqualified ordinal selection."""
    latest = scoped_messages_query(db,conversation).filter_by(direction='outbound').filter(
        SalesMessage.status.notin_(['failed','cancelled'])).order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    if not latest:
        return []
    meta = latest.metadata_json or {}
    if meta.get('lead_id',conversation.lead_id) != conversation.lead_id:
        return []
    offers = []
    catalog = meta.get('property_catalog_offer') or {}
    ids = catalog.get('property_type_ids') or []
    if ids and len(ids)<=200:
        from app.modules.projects.models import ProjectPropertyType
        count = db.query(ProjectPropertyType.id).filter(ProjectPropertyType.project_id==conversation.project_id,
            ProjectPropertyType.id.in_(ids)).count()
        if count == len(ids):
            offers.append(Offer(kind='property',message_id=latest.id,option_ids=ids))
    slots = (meta.get('appointment_offer') or {}).get('slots') or []
    if slots and len(slots)<=200 and all(isinstance(s,str) for s in slots):
        at = latest.created_at.replace(tzinfo=timezone.utc) if latest.created_at.tzinfo is None else latest.created_at
        offers.append(Offer(kind='appointment',message_id=latest.id,option_ids=slots,expires_at=at+timedelta(minutes=30)))
    return offers

logger = logging.getLogger(__name__)


async def observe_shadow(db, conversation, inbound):
    if not (settings.SALES_DIALOGUE_RUNTIME_ENABLED and settings.SALES_UNDERSTANDING_PREVIEW_ENABLED):
        return 'disabled'
    try:
        config = db.query(AIConfiguration).filter_by(company_id=None).first()
        policy = RuntimePolicy.model_validate((config.agent_ventas or {}).get('runtime_config') or {}) if config else RuntimePolicy()
        scope = Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
        if not policy.selects(scope):
            return 'not_selected'
        key = 'shadow-draft:'+inbound.id
        if scope.query(db,SalesDialogueEvent).filter_by(event_key=key).first():
            return 'replayed'
        if scope.query(db,SalesDialogueEvent).filter_by(event_key='shadow-error:'+inbound.id).first():
            return 'shadow_error'
        previous = scope.query(db,SalesDialogueEvent).filter_by(event_key='shadow-understanding:'+inbound.id).first()
        if previous and previous.payload_json['metadata'].get('outcome') != 'accepted':
            return previous.payload_json['metadata']['outcome']
        connection = db.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN')
        with db.begin_nested():
            revision,state = load(db,scope)
            offers = recorded_offers(db,conversation)
            if state.offers != offers:
                state.offers = offers
                revision,state = save(db,scope,event_key='shadow-offers:'+inbound.id,expected_revision=revision,state=state,
                    metadata={'message_id':inbound.id,'source':'latest_scoped_outbound','external_actions':0})
            interpreted = await asyncio.wait_for(preview(db,scope,inbound_message_id=inbound.id,expected_revision=revision,
                event_key='shadow-understanding:'+inbound.id),timeout=policy.max_seconds)
            if interpreted.status != 'accepted':
                return interpreted.status
            outcome = run_turn(db,scope,message_id=inbound.id,understanding=interpreted.state.last_understanding,
                expected_revision=interpreted.revision,event_key='shadow-runtime:'+inbound.id,
                max_steps=policy.max_steps,max_seconds=policy.max_seconds)
            draft = compose(outcome,channel=conversation.channel,style=policy.composition_style)
            save(db,scope,event_key=key,expected_revision=outcome.revision,state=outcome.state,
                metadata={'engine':'shadow/1.0','message_id':inbound.id,'draft':asdict(draft),
                    'published_configuration_id':config.id,'runtime_policy':policy.model_dump(),
                    'external_actions':0,'not_dispatched':True})
        return 'recorded'
    except Exception as exc:
        # Do not replace a legacy reply, pause a lead or leak provider errors.
        logger.warning('sales_shadow_failed code=%s',type(exc).__name__)
        try:
            revision,state = load(db,scope)
            if not scope.query(db,SalesDialogueEvent).filter_by(event_key='shadow-error:'+inbound.id).first():
                save(db,scope,event_key='shadow-error:'+inbound.id,expected_revision=revision,state=state,
                    metadata={'message_id':inbound.id,'engine':'shadow/1.0','error_code':type(exc).__name__,
                        'not_dispatched':True,'external_actions':0})
        except Exception:
            logger.warning('sales_shadow_error_evidence_unavailable')
        return 'shadow_error'
