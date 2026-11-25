"""P08 isolated Hermes simulation execution. NEVER a production messaging route.

This is an intentionally narrow SDK-worker integration point. It cannot run on
SMS/WhatsApp threads, cannot enqueue provider messages, and cannot use non-demo
leads. A single database transaction records the exact visible in-app reply and
its Hermes state event. The caller owns the DB connection; this function commits
only after both records have been flushed and independently verified.

Do not route real inbound queues to this function. A production Hermes effect
adapter and provider-receipt end-to-end certification are not included here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from .bp_context import require_scoped_entities
from .contracts import TurnScope


class P08SimulationNotReady(PermissionError):
    """Selected conversation is not authorized for isolated Hermes simulation."""


def _existing_receipt(db, scope: TurnScope, inbound_message_id: str):
    from .bp_models import HermesSalesStateEvent
    # Never infer a receipt from a tool response or a prospective message.
    return db.query(HermesSalesStateEvent).filter_by(
        conversation_id=scope.conversation_id, lead_id=scope.lead_id,
        event_key='hermes:sim:' + inbound_message_id,
        event_type='simulation_receipt',
    ).one_or_none()


def _replies(db, scope: TurnScope, inbound_message_id: str):
    from app.modules.sales_agent.models import SalesMessage
    return db.query(SalesMessage).filter_by(
        conversation_id=scope.conversation_id, channel='simulation',
        direction='outbound', role='assistant',
    ).filter(
        SalesMessage.metadata_json['hermes_inbound_message_id'].as_string() == inbound_message_id,
    ).order_by(SalesMessage.created_at, SalesMessage.id).all()


def _preflight(db, scope: TurnScope, inbound_message_id: str):
    from app.modules.sales_agent.models import SalesConversation, SalesMessage
    # PostgreSQL row lock serializes staged turns from this conversation; it is
    # deliberately held during model invocation ONLY in this small test lane.
    conversation = db.query(SalesConversation).filter_by(
        id=scope.conversation_id, company_id=scope.company_id,
        project_id=scope.project_id, lead_id=scope.lead_id,
    ).with_for_update().one_or_none()
    _, _, lead, selected = require_scoped_entities(db, scope)
    if not conversation or selected.id != conversation.id or conversation.channel != 'simulation':
        raise P08SimulationNotReady('Only a scoped in-app simulation conversation is supported')
    if not lead.is_demo or lead.is_opt_out or lead.consent_status not in {'granted', 'granted_simulation'}:
        raise P08SimulationNotReady('A consenting demo lead is required')
    if getattr(lead, 'agent_status', None) == 'human_control' or getattr(conversation, 'is_paused', False):
        raise P08SimulationNotReady('Human control or paused conversations are not executable')
    inbound = db.query(SalesMessage).filter_by(
        id=inbound_message_id, conversation_id=scope.conversation_id,
        direction='inbound', role='user', channel='simulation',
    ).one_or_none()
    if (inbound is None or inbound.status not in {'received', 'processed'}
            or (inbound.metadata_json or {}).get('lead_id') != scope.lead_id
            or not isinstance(inbound.content, str) or not inbound.content.strip()):
        raise P08SimulationNotReady('Only a persisted attributable simulation inbound is valid')
    return inbound


def execute_staged_simulation(db, scope: TurnScope, *, inbound_message_id: str,
                              settings, enabled_tools: frozenset[str],
                              published_version_id: str,
                              prepare=None, commit=None) -> dict[str, Any]:
    """Single-entry P08 SDK-staging operation (not connected to a customer route).

    Returns a durable in-app reply after a successful commit. All exceptions
    roll back the transaction. The caller must not keep unrelated pending ORM
    mutations in this session. A replay returns the original reply without
    invoking the SDK, even if Staff subsequently publishes a different prompt.
    """
    from app.modules.sales_agent.models import SalesMessage
    from .bp_p04_turn import prepare_p04_simulation_turn, commit_p04_simulation_receipt

    if not isinstance(published_version_id, str) or not published_version_id:
        raise P08SimulationNotReady('A published global Hermes version is required')
    if not isinstance(enabled_tools, frozenset):
        raise TypeError('Pinned global tool policy must be a frozenset')
    if not isinstance(inbound_message_id, str) or not 1 <= len(inbound_message_id) <= 36:
        raise ValueError('Invalid inbound message identifier')
    try:
        inbound = _preflight(db, scope, inbound_message_id)
        existing = _replies(db, scope, inbound.id)
        if existing:
            receipt = _existing_receipt(db, scope, inbound.id)
            if (len(existing) != 1 or not receipt or existing[0].status != 'sent'
                    or (existing[0].metadata_json or {}).get('engine') != 'hermes-agent'
                    or (existing[0].metadata_json or {}).get('lead_id') != scope.lead_id
                    or not existing[0].content):
                raise P08SimulationNotReady('Incomplete Hermes reply requires manual review, not retry')
            return {'message_id': existing[0].id, 'reply': existing[0].content,
                    'replayed': True, 'delivery': 'in_app_only',
                    'published_version_id': (existing[0].metadata_json or {}).get('hermes_version_id')}

        preparer = prepare or prepare_p04_simulation_turn
        committer = commit or commit_p04_simulation_receipt
        prepared = preparer(db, scope, inbound_message_id=inbound.id,
                            settings=settings, enabled_tools=enabled_tools)
        reply = prepared.prepared.result.reply
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError('Hermes returned an empty answer')
        # No SMS/WhatsApp sender, Calendar API or asset-share service is called
        # here. A tool's proposed effect is not equivalent to a confirmed effect.
        output = SalesMessage(
            id=str(uuid4()), conversation_id=scope.conversation_id, channel='simulation',
            direction='outbound', role='assistant', status='sent', content=reply,
            metadata_json={'lead_id': scope.lead_id,
                           'hermes_inbound_message_id': inbound.id,
                           'engine': 'hermes-agent',
                           'hermes_version_id': published_version_id,
                           'delivery_kind': 'in_app_only',
                           'simulated_effects_only': True},
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        # Existing BP model has provider_message_id (unique by channel). The
        # minimal P03 SQLAlchemy stand-in does not; its absence is test-only.
        if hasattr(SalesMessage, 'provider_message_id'):
            output.provider_message_id = 'hermes:p08:' + inbound.id
        db.add(output)
        db.flush()
        committed = committer(db, prepared, outbound_message_id=output.id)
        if not _existing_receipt(db, scope, inbound.id) or committed.revision <= 0:
            raise RuntimeError('Exact Hermes state/delivery receipt was not persisted')
        db.commit()
        return {'message_id': output.id, 'reply': reply.strip(), 'replayed': False,
                'delivery': 'in_app_only', 'published_version_id': published_version_id,
                'state_revision': committed.revision}
    except BaseException:
        db.rollback()
        raise
