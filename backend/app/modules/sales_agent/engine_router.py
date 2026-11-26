"""HEI-01A Sales dispatch boundary. Does not execute Hermes or business effects.

Production Hermes is gated until the runtime and real effect receipts are
certified. Existing job handlers retain consent, scope, provider and effect
checks. A pin belongs to an event/opportunity, not the phone or entire thread.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from app.modules.hermes_sales_core.engine_selection import (
    ENGINES, HERMES, LANGGRAPH, EngineSelectionError, EngineUnavailable,
    require_selectable,
)

PIN_KEY = 'sales_engine_pin'


def event_scope(conversation, event_id: str) -> dict[str, str]:
    return dict(event_id=event_id, conversation_id=conversation.id,
                company_id=conversation.company_id, project_id=conversation.project_id,
                lead_id=conversation.lead_id)


def engine_from_run(graph_version: str) -> str:
    """All historical AgentRun versions in this baseline are legacy except Hermes.

    Pass historical legacy runs back to their original coordinator's existing
    reconciliation guard; never rewrite their graph version or checkpoint.
    """
    if not isinstance(graph_version, str) or not graph_version:
        raise EngineSelectionError('Historical agent run has no engine identity.')
    return HERMES if graph_version.lower().startswith('hermes') else LANGGRAPH


def decide(*, scope: dict[str, str], status: dict[str, Any],
           pin: dict | None = None, run=None) -> dict[str, Any]:
    """Return a validated, stable event pin; an existing run/pin wins over a switch.

    Do not call a second engine when the recorded engine is not ready.
    """
    stored = None
    if pin is not None:
        if not isinstance(pin, dict) or any(pin.get(k) != v for k, v in scope.items()):
            raise EngineSelectionError('Engine pin does not belong to this event and opportunity.')
        stored = pin.get('engine')
        if not isinstance(stored, str) or stored not in ENGINES:
            raise EngineSelectionError('Invalid persisted engine pin.')
    if run is not None:
        if run.conversation_id != scope['conversation_id'] or run.event_id != scope['event_id']:
            raise EngineSelectionError('Agent run belongs to a different event or conversation.')
        original = engine_from_run(run.graph_version)
        if stored is not None and stored != original:
            raise EngineSelectionError('Engine pin conflicts with the existing agent run.')
        stored = original
    engine = stored if stored is not None else status.get('active_sales_engine')
    if not isinstance(engine, str) or engine not in ENGINES:
        raise EngineSelectionError('No valid sales engine selected; staff review required.')
    # Existing events are never silently replayed through another engine.
    require_selectable(engine)
    policy_version = (pin or {}).get('policy_version_id') if pin is not None else (
        getattr(run, 'prompt_configuration_id', None) if run is not None else
        status.get('published_version_id') if engine == HERMES else None)
    return {**scope, 'engine': engine, 'policy_version_id': policy_version}


def resolve(db, conversation, event_id: str, *, pin: dict | None = None, run=None):
    from .models import AgentRun
    from app.modules.hermes_sales_core.staff_config import engine_status
    if run is None:
        run = db.query(AgentRun).filter_by(event_id=event_id).first()
    return decide(scope=event_scope(conversation, event_id), status=engine_status(db),
                  pin=pin, run=run)


async def route_live_job(job_id: str, *, inbound: bool,
                         legacy_handler: Callable[[str], Awaitable[None]]) -> bool:
    """Route the existing claimed worker job; never run an SDK in the API.

    Pin in the already persisted message/job JSON before the old handler starts.
    Close the routing transaction before invoking the business handler. A missing
    registry/table or DB failure propagates to the existing worker recovery path
    instead of guessing a different engine.
    """
    from app.db.postgres import SessionLocal
    from .concurrency import bounded
    from .models import SalesConversation, SalesFollowUpJob, SalesInboundJob
    from .conversation_scope import scoped_messages_query
    from app.modules.sales_crm.models import Lead

    db = bounded(SessionLocal())
    job_model = SalesInboundJob if inbound else SalesFollowUpJob
    should_dispatch = False
    try:
        # Read claimed job; lock conversation before job to align with provider
        # intake/continuity code. Recheck claim after locks are acquired.
        job = db.get(job_model, job_id)
        if not job or job.status != 'processing':
            return False
        conversation = db.query(SalesConversation).filter_by(id=job.conversation_id).with_for_update().first()
        job = db.query(job_model).filter_by(id=job_id).populate_existing().with_for_update().first()
        if not job or job.status != 'processing':
            return False
        if not conversation or conversation.id != job.conversation_id:
            job.status = 'cancelled'
            job.processed_at = datetime.utcnow()
            db.commit()
            return False
        lead = db.get(Lead, conversation.lead_id)
        if not lead or lead.deleted_at or lead.company_id != conversation.company_id or lead.project_id != conversation.project_id:
            job.status = 'cancelled'
            job.processed_at = datetime.utcnow()
            db.commit()
            return False
        if inbound:
            message = scoped_messages_query(db, conversation).filter_by(
                id=job.message_id, direction='inbound', role='user').first()
            if not message:
                job.status = 'cancelled'
                job.processed_at = datetime.utcnow()
                db.commit()
                return False
            payload = dict(message.metadata_json or {})
            # Missing attribution is permitted only for existing scoped history;
            # an explicit mismatched opportunity is never re-routed.
            if (payload.get('lead_id', conversation.lead_id) != conversation.lead_id or
                    payload.get('project_id', conversation.project_id) != conversation.project_id):
                job.status = 'cancelled'
                job.processed_at = datetime.utcnow()
                db.commit()
                return False
            event_id = f'{conversation.provider}:{message.provider_message_id or message.id}'
        else:
            payload = dict(job.payload_json or {})
            kind = job.kind or 'cadence'
            event_id = f'resume:{job.id}' if kind == 'resume' else (
                f'inactivity:{job.id}' if kind == 'inactivity' else f'followup:{job.id}')
            # Preserve old continuity ownership checks; never reuse a pin for a
            # different active opportunity in the same physical provider thread.
            if (payload.get('lead_id', conversation.lead_id) != conversation.lead_id or
                    payload.get('project_id', conversation.project_id) != conversation.project_id):
                job.status = 'cancelled'
                job.processed_at = datetime.utcnow()
                db.commit()
                return False
        try:
            pin = resolve(db, conversation, event_id, pin=payload.get(PIN_KEY))
            if pin['engine'] != LANGGRAPH:
                # Defense in depth: a future change to readiness is not itself
                # a live handler. This package cannot dispatch Hermes yet.
                raise EngineUnavailable('No certified Hermes live handler is installed.')
        except (EngineSelectionError, EngineUnavailable) as exc:
            code = 'HERMES_NOT_READY' if isinstance(exc, EngineUnavailable) else 'ENGINE_SELECTION_REVIEW'
            job.status = 'review'
            job.processed_at = datetime.utcnow()
            if inbound:
                job.error_code = code
                job.error_message = 'Sales engine routing requires staff review.'
                message.metadata_json = {**payload, 'agent_turn_status': 'review',
                                         'agent_turn_error': job.error_message}
            else:
                job.reason = code.lower()
                job.payload_json = {**payload, 'engine_routing_error': code}
            db.commit()
            return False
        if inbound:
            message.metadata_json = {**payload, PIN_KEY: pin}
        else:
            job.payload_json = {**payload, PIN_KEY: pin}
        db.commit()
        should_dispatch = True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    if should_dispatch:
        await legacy_handler(job_id)
        return True
    return False
