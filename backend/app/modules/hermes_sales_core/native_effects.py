"""HEI-03A: isolated native business-effect gateway for a completed Hermes turn.

Not a live engine, webhook, or provider dispatcher. The model proposes; the
existing P04 executor owns business validation and demo-only effects. A dedicated
worker transaction links the immutable operation receipt to the originating run.
No schema changes, no new booking/asset service, no bearer URLs in diagnostics.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4


class NativeEffectError(PermissionError):
    """The proposed effect is not authorized or cannot be safely replayed."""


TOOLS = {'book': 'book_onsite_visit', 'cancel': 'cancel_onsite_visit',
         'reschedule': 'reschedule_onsite_visit', 'material': 'get_unit_media'}
STATUSES = {'book': 'confirmed', 'cancel': 'cancelled', 'reschedule': 'rescheduled',
            'material': 'link_issued_for_simulation'}


def pending_effect(state: dict, inbound_id: str) -> dict | None:
    """Read only the exact turn's pending state, not an LLM reply/argument."""
    confirmation = state.get('confirmation_request') or {}
    material = (state.get('offered_assets') or {}).get('pending_request') or {}
    candidates = []
    if (confirmation.get('kind') in ('book', 'cancel', 'reschedule') and
            confirmation.get('status') == 'execution_requested' and
            confirmation.get('confirmed_inbound_message_id') == inbound_id):
        candidates.append({'kind': confirmation['kind'], 'request_id': confirmation.get('id'),
                           'draft': confirmation})
    if material.get('source_inbound_message_id') == inbound_id:
        candidates.append({'kind': 'material', 'request_id': material.get('id'), 'draft': material})
    if len(candidates) > 1:
        raise NativeEffectError('Multiple simultaneous effects require separate buyer turns.')
    if not candidates:
        return None
    candidate = candidates[0]
    if not isinstance(candidate['request_id'], str) or not 1 <= len(candidate['request_id']) <= 64:
        raise NativeEffectError('Invalid prepared request ID.')
    if candidate['kind'] == 'material':
        ids = material.get('asset_ids')
        if (not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str)
                or not ids[0]):
            raise NativeEffectError('Single verified material required; batch delivery is not enabled.')
        candidate['asset_id'] = ids[0]
    return candidate


def pending_reply(state: dict, inbound_id: str, reply: str) -> str:
    """A pending tool result must never be presented as a completed effect.

    Only alter replies for this inbound's prepared effects; leave exploration,
    property menus and confirmation recaps to Hermes. The backend's actual
    operation receipt is a separate message, not an invented model success.
    """
    try:
        candidate = pending_effect(state, inbound_id)
    except NativeEffectError:
        return 'Please choose one specific action or material so I can check it.'
    if not candidate:
        return reply
    if candidate['kind'] == 'material':
        return 'I found the requested material. I still need to validate the share before sending it.'
    if candidate['kind'] == 'cancel':
        return 'I will check the cancellation of your visit. It is not cancelled yet.'
    if candidate['kind'] == 'reschedule':
        return 'I will check the new visit time. Your appointment has not been changed yet.'
    return 'I will check whether your selected visit can be confirmed. It is not booked yet.'


def _receipt_text(kind, draft):
    if kind == 'material':
        # P04 issues a bearer token but does NOT deliver it. Do not publish it
        # in chat history, logs, or diagnostic JSON. Actual share delivery is 03B.
        return 'Test material access was issued in the isolated environment. No document has been sent.'
    if kind == 'cancel':
        return 'Your test visit was cancelled in the simulation. No external calendar was changed.'
    action = 'rescheduled' if kind == 'reschedule' else 'confirmed'
    return (f'Your test visit was {action} for {draft["date"]} at {draft["start_time"]} '
            f'({draft["timezone"]}) in the simulation. No external calendar was changed.')


def _validate_run(db, scope, conversation, inbound_id):
    from app.modules.sales_agent.models import AgentRun
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    from .staged_runtime import ENGINE_VERSION, _validate_inbound
    from .p08_simulation import _existing_receipt, _replies

    inbound = _validate_inbound(db, scope, conversation, inbound_id)
    run = db.query(AgentRun).filter_by(event_id=inbound.provider_message_id,
                                      conversation_id=conversation.id).populate_existing().with_for_update().one_or_none()
    pin = (inbound.metadata_json or {}).get(PIN_KEY) or {}
    if (not run or run.status != 'completed' or run.mode != 'simulation'
            or run.graph_version != ENGINE_VERSION or pin.get('engine') != 'hermes'
            or any(pin.get(k) != v for k, v in event_scope(conversation, inbound.provider_message_id).items())
            or pin.get('policy_version_id') != run.prompt_configuration_id
            or (run.input_snapshot or {}).get(PIN_KEY) != pin
            or (run.input_snapshot or {}).get('message_id') != inbound.id):
        raise NativeEffectError('A completed, pinned isolated Hermes turn is required.')
    replies = _replies(db, scope, inbound.id)
    receipt = _existing_receipt(db, scope, inbound.id)
    out = run.output_snapshot or {}
    meta = out.get('metadata') or {}
    if (len(replies) != 1 or not receipt or replies[0].status != 'sent'
            or (replies[0].metadata_json or {}).get('lead_id') != scope.lead_id
            or (replies[0].metadata_json or {}).get('engine') != 'hermes-agent'
            or (replies[0].metadata_json or {}).get('agent_run_id') != run.id
            or (replies[0].metadata_json or {}).get('hermes_version_id') != run.prompt_configuration_id
            or meta.get('message_id') != replies[0].id or out.get('reply') != replies[0].content
            or meta.get('state_revision') != receipt.revision):
        raise NativeEffectError('The original turn lacks an exact durable message/state receipt.')
    return inbound, run, replies[0], receipt


def _operation_query(db, scope, inbound_id):
    from .bp_operation_models import HermesSalesOperation
    return db.query(HermesSalesOperation).filter_by(**scope.__dict__, inbound_message_id=inbound_id)


def _replay(db, scope, run, inbound_id, meta):
    from app.modules.sales_agent.models import SalesMessage
    op = _operation_query(db, scope, inbound_id).filter_by(id=meta.get('operation_id')).one_or_none()
    message = db.get(SalesMessage, meta.get('receipt_message_id'))
    kind = meta.get('kind')
    if (not op or op.status != 'completed' or kind not in STATUSES
            or op.operation_type != kind or op.request_id != meta.get('request_id')
            or (op.result_json or {}).get('status') != STATUSES[kind]
            or not message or message.conversation_id != scope.conversation_id
            or message.channel != 'simulation' or message.direction != 'outbound'
            or message.role != 'assistant' or message.status != 'sent'
            or (message.metadata_json or {}).get('lead_id') != scope.lead_id
            or (message.metadata_json or {}).get('agent_run_id') != run.id
            or (message.metadata_json or {}).get('native_operation_id') != op.id
            or (message.metadata_json or {}).get('native_inbound_id') != inbound_id
            or sha256((message.content or '').encode()).hexdigest() != meta.get('receipt_sha256')):
        raise NativeEffectError('Inconsistent native operation receipt; review instead of retrying.')
    ids = meta.get('business_ids') or {}
    if not isinstance(ids, dict) or not ids or any((op.result_json or {}).get(k) != v for k, v in ids.items()):
        raise NativeEffectError('Stored business identifiers differ from the native receipt.')
    return {**meta, 'replayed': True}


def _assert_business_policy(db, scope, kind):
    # Preserve the existing approved Company/Project restrictions. Do not turn
    # a successful Hermes draft into a waiver of business compliance.
    from app.modules.projects.models import Project
    from app.modules.sales_agent.commercial_context import confirmed_profile_facts
    from app.modules.sales_agent.sales_policy import policy_context, compliance_action_holds
    project = db.get(Project, scope.project_id)
    if not project:
        raise NativeEffectError('Project is not available.')
    holds = compliance_action_holds(policy_context(db, scope, confirmed_profile_facts(project.profile)))
    if ('materials' if kind == 'material' else 'appointment') in holds:
        raise NativeEffectError('The current business policy requires human review.')


def _effect_ids(kind, candidate, record):
    keys = {'book': ('meeting_id', 'booking_operation_id'),
            'cancel': ('meeting_id', 'cancellation_operation_id'),
            'reschedule': ('meeting_id', 'original_meeting_id', 'reschedule_operation_id'),
            'material': ('asset_id', 'share_id')}[kind]
    if any(not isinstance(record.get(key), str) or not record[key] for key in keys):
        raise NativeEffectError('Native receipt is missing business identifiers.')
    if kind == 'material' and (record['asset_id'] != candidate['asset_id'] or record.get('delivery') != 'not_sent'):
        raise NativeEffectError('Material receipt does not match the requested asset.')
    if kind != 'material' and record.get('calendar_status') != 'simulation':
        raise NativeEffectError('The native appointment receipt is not simulation-only.')
    return {key: record[key] for key in keys}


def execute_native_effect(db, scope, *, inbound_message_id: str) -> dict[str, Any]:
    """Execute ONE authorized P04 demo effect after an exact HEI-01B turn.

    Use a dedicated DB session against an isolated test/staging database.
    The original turn stays committed even if this separate effect fails.
    The operation, visible safe receipt and AgentRun attribution commit together.
    Retrying the same command returns the existing receipt without calling P04.
    The function deliberately never sends an SMS/WhatsApp, calendar event, or URL.
    """
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from .staged_runtime import require_staging_database, _lock_conversation, _policy
    from .staff_config import snapshot
    from .bp_state_store import load
    from .bp_effect_executor import execute_p04_simulation_operation

    require_staging_database(db)
    try:
        conversation = _lock_conversation(db, scope)
        inbound, run, original, receipt = _validate_run(db, scope, conversation, inbound_message_id)
        output = run.output_snapshot or {}
        previous = output.get('native_effect')
        if previous is not None:
            result = _replay(db, scope, run, inbound.id, previous)
            db.commit()
            return result
        if _operation_query(db, scope, inbound.id).count():
            raise NativeEffectError('A previous operation lacks HEI-03A attribution; manual review required.')
        loaded = load(db, scope)
        if loaded.revision != receipt.revision:
            raise NativeEffectError('A newer state exists; do not execute an old proposal.')
        # An intervening inbound or manual/legacy message invalidates the turn.
        latest = scoped_messages_query(db, conversation).order_by(
            SalesMessage.created_at.desc(), SalesMessage.id.desc()).first()
        if not latest or latest.id != original.id:
            raise NativeEffectError('The proposal is not from the latest delivered turn.')
        candidate = pending_effect(loaded.data, inbound.id)
        if candidate is None:
            db.commit()
            return {'status': 'no_effect_requested', 'replayed': False}
        kind = candidate['kind']
        tool = TOOLS[kind]
        policy = _policy(db, run.prompt_configuration_id)
        current = snapshot(db)
        if (not current['configuration'].get('enabled') or not current['published_version_id']
                or tool not in policy.enabled_tools or tool not in current['configuration'].get('enabled_tools', ())
                or not any(x.get('tool') == tool and x.get('status') == 'executed'
                           for x in output.get('tool_observations', []) if isinstance(x, dict))):
            raise NativeEffectError('The originating and current tool policies must authorize the action.')
        _assert_business_policy(db, scope, kind)
        # Make the SQLite outer transaction explicit before the P04 savepoint.
        connection = db.connection()
        if (connection.dialect.name == 'sqlite'
                and not connection.connection.driver_connection.in_transaction):
            connection.exec_driver_sql('BEGIN')
        result = execute_p04_simulation_operation(db, scope, expected_revision=loaded.revision,
            inbound_message_id=inbound.id, **({'asset_id': candidate['asset_id']} if kind == 'material' else {}))
        # P04's return value is not the authority. Read its committed-in-this-
        # transaction operation record and verify the same exact action.
        op = _operation_query(db, scope, inbound.id).filter_by(request_id=candidate['request_id']).one_or_none()
        if (not op or op.status != 'completed' or op.operation_type != kind
                or result.get('replayed') or result.get('status') != STATUSES[kind]
                or (op.result_json or {}).get('status') != STATUSES[kind]):
            raise NativeEffectError('No verified native operation receipt.')
        identifiers = _effect_ids(kind, candidate, op.result_json)
        if any(result.get(k) != v for k, v in identifiers.items()):
            raise NativeEffectError('Operation result differs from its stored business receipt.')
        revised = load(db, scope)
        if revised.revision != loaded.revision + 1:
            raise NativeEffectError('The effect must advance the persisted Hermes state exactly once.')
        # Separate provider_message_id and metadata key: never make the P08
        # original reply lookup see two model replies for the same inbound.
        message = SalesMessage(id=str(uuid4()), conversation_id=conversation.id,
            channel='simulation', direction='outbound', role='assistant', status='sent',
            provider_message_id='hermes:native:' + op.id,
            content=_receipt_text(kind, candidate['draft']),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            metadata_json={'lead_id': scope.lead_id, 'project_id': scope.project_id,
                'engine': 'hermes-agent', 'agent_run_id': run.id, 'native_operation_id': op.id,
                'native_inbound_id': inbound.id, 'runtime_lane': 'isolated_simulation',
                'delivery_kind': 'in_app_only', 'simulated_effects_only': True})
        db.add(message)
        db.flush()
        # Allowlist only IDs/status. In particular, discard P04's ephemeral URL.
        safe = {'status': STATUSES[kind], 'kind': kind, 'request_id': op.request_id,
                'operation_id': op.id, 'receipt_message_id': message.id,
                'receipt_sha256': sha256(message.content.encode()).hexdigest(),
                'business_ids': identifiers,
                'state_revision': revised.revision, 'delivery': 'in_app_only',
                'external_effects': False, 'material_delivery': 'not_sent' if kind == 'material' else None}
        run.output_snapshot = {**output, 'native_effect': safe}
        db.flush()
        db.commit()
        return {**safe, 'replayed': False}
    except BaseException:
        db.rollback()
        raise
