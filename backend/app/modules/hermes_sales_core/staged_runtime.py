"""HEI-01B: isolated, explicitly selected Hermes simulation turns.

The global production selector remains unchanged. This is NOT a webhook,
production job handler or effect executor. Reuse P08's transactional receipt,
P05's immutable policy history, and HEI-01A's event identity/pin. No migration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePath
import os
import re
from uuid import uuid4

from .contracts import TurnScope
from .config import HermesSettings
from .engine_selection import prompt_policy
from app.modules.sales_agent.engine_router import PIN_KEY, decide_staged_hermes

ENGINE_VERSION = 'hermes/hei-01b'
TOOLSET_VERSION = 'hermes-tools/1.0'
NEW_EVENT_PREFIX = 'hermes:staged:'


class StagedRuntimeError(PermissionError):
    """An isolated turn cannot safely run/replay under the requested identity."""


def require_staging_database(db, *, environment: str | None = None) -> None:
    """Defense in depth; do not pass a production URL to this worker at all.

    Check the actual bound database, not just the configured ENVIRONMENT.
    Naming is only a guard, not proof that a server is non-production.
    """
    env = (environment if environment is not None else os.environ.get('ENVIRONMENT', '')).lower()
    if env not in {'test', 'staging'}:
        raise StagedRuntimeError('Hermes isolated runtime requires test or staging.')
    bind = db.get_bind()
    url = getattr(bind, 'url', None) or getattr(getattr(bind, 'engine', None), 'url', None)
    if url is None:
        raise StagedRuntimeError('Cannot verify the isolated database target.')
    database = (url.database or '')
    if url.get_backend_name() == 'sqlite' and database == ':memory:' and env == 'test':
        return
    name = PurePath(database).name.lower()
    parts = set(re.split(r'[^a-z0-9]+', name))
    if not parts.intersection({'test', 'staging'}) or parts.intersection({'prod', 'production', 'live'}):
        raise StagedRuntimeError('Database name must explicitly identify test or staging, never production.')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _policy(db, version_id):
    from .staff_config import find_version, HermesGlobalPolicy
    if not version_id:
        raise StagedRuntimeError('Publish an enabled Hermes configuration first.')
    try:
        version = find_version(db, version_id)
    except LookupError as exc:
        raise StagedRuntimeError('Pinned Hermes policy no longer exists.') from exc
    # is_published may now be False: a previously published immutable version
    # is valid for a retry. A never-published draft must never run.
    if not version.published_at:
        raise StagedRuntimeError('Pinned Hermes policy was never published.')
    policy = HermesGlobalPolicy.model_validate(prompt_policy(version.configuration))
    if not policy.enabled:
        raise StagedRuntimeError('Pinned Hermes policy is disabled.')
    return policy


def _lock_conversation(db, scope):
    from app.modules.sales_agent.models import SalesConversation
    from .bp_context import require_scoped_entities
    conversation = db.query(SalesConversation).filter_by(**dict(
        id=scope.conversation_id, company_id=scope.company_id,
        project_id=scope.project_id, lead_id=scope.lead_id,
    )).populate_existing().with_for_update().one_or_none()
    if not conversation or conversation.channel != 'simulation':
        raise StagedRuntimeError('Only a scoped simulation conversation is supported.')
    _, _, lead, _ = require_scoped_entities(db, scope)
    if (not lead.is_demo or lead.is_opt_out or lead.deleted_at or
            lead.consent_status not in {'granted', 'granted_simulation'} or
            lead.agent_status == 'human_control' or conversation.is_paused):
        raise StagedRuntimeError('A consenting, active, unpaused demo opportunity is required.')
    return conversation


def _new_inbound(db, scope, conversation, event_id, message):
    from app.modules.sales_agent.models import SalesMessage
    if (not isinstance(event_id, str) or not event_id.startswith(NEW_EVENT_PREFIX) or
            len(event_id) > 180 or not re.fullmatch(r'[A-Za-z0-9:_-]+', event_id)):
        raise ValueError('New event ID must use hermes:staged:<unique-id> (max 180 characters).')
    if not isinstance(message, str) or not message.strip() or len(message.encode('utf-8')) > 12000:
        raise ValueError('Buyer message must be nonempty and at most 12000 UTF-8 bytes.')
    existing = db.query(SalesMessage).filter_by(channel='simulation', provider_message_id=event_id).one_or_none()
    if existing is not None:
        if (existing.conversation_id != conversation.id or existing.direction != 'inbound' or
                existing.role != 'user' or existing.content != message or
                (existing.metadata_json or {}).get('lead_id') != scope.lead_id):
            raise StagedRuntimeError('The event ID already belongs to another message.')
        return existing
    inbound = SalesMessage(id=str(uuid4()), conversation_id=conversation.id,
        channel='simulation', direction='inbound', role='user', content=message,
        status='received', provider_message_id=event_id, created_at=_now(),
        metadata_json={'lead_id': scope.lead_id, 'project_id': scope.project_id,
                       'simulation': True, 'hermes_staged': True})
    db.add(inbound)
    db.flush()
    return inbound


def _validate_inbound(db, scope, conversation, inbound_id):
    from .p08_simulation import _preflight
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    inbound = _preflight(db, scope, inbound_id)
    if not scoped_messages_query(db, conversation).filter_by(id=inbound.id).first():
        raise StagedRuntimeError('Inbound is outside the active opportunity.')
    if (inbound.metadata_json or {}).get('project_id', scope.project_id) != scope.project_id:
        raise StagedRuntimeError('Inbound belongs to another project.')
    # Use the SAME event ID the existing simulation route uses. Without it we
    # cannot establish that the legacy route has not already handled this input.
    if not inbound.provider_message_id or len(inbound.provider_message_id) > 180:
        raise StagedRuntimeError('A persisted simulation event ID is required.')
    return inbound


def _reserve(db, scope, *, inbound_message_id, event_id, message):
    from app.modules.sales_agent.models import AgentRun
    from .staff_config import snapshot
    from .p08_simulation import _replies, _existing_receipt

    conversation = _lock_conversation(db, scope)
    if inbound_message_id is None:
        inbound_message_id = _new_inbound(db, scope, conversation, event_id, message).id
    inbound = _validate_inbound(db, scope, conversation, inbound_message_id)
    actual_event = inbound.provider_message_id
    run = db.query(AgentRun).filter_by(event_id=actual_event).populate_existing().one_or_none()
    previous_pin = (inbound.metadata_json or {}).get(PIN_KEY)
    current = snapshot(db)
    pin = decide_staged_hermes(conversation, actual_event,
        published_version_id=current['published_version_id'], pin=previous_pin, run=run)
    replies = _replies(db, scope, inbound.id)
    receipt = _existing_receipt(db, scope, inbound.id)
    if run is None and (previous_pin is not None or replies or receipt):
        raise StagedRuntimeError('Existing state/output has no HEI-01B run; staff review required.')
    if run is not None:
        if (previous_pin != pin or run.graph_version != ENGINE_VERSION or
                (run.input_snapshot or {}).get(PIN_KEY) != pin or
                (run.input_snapshot or {}).get('message_id') != inbound.id):
            raise StagedRuntimeError('Existing run lacks the exact staged turn pin.')
        if run.status not in {'running', 'failed', 'completed'}:
            raise StagedRuntimeError('Existing run requires staff review.')
        if run.status == 'completed' and (len(replies) != 1 or receipt is None):
            raise StagedRuntimeError('Completed run has no exact receipt; staff review required.')
    policy = _policy(db, pin['policy_version_id'])
    if not replies and not receipt:
        # New inference, including retries, needs current permission. It uses
        # the original policy, not the new prompt if another version was published.
        if not current['configuration'].get('enabled') or not current['published_version_id']:
            raise StagedRuntimeError('Current Hermes configuration is disabled.')
    if run is None:
        run = AgentRun(conversation_id=conversation.id, event_id=actual_event,
            mode='simulation', status='running', graph_version=ENGINE_VERSION,
            toolset_version=TOOLSET_VERSION, model=policy.model,
            prompt_configuration_id=pin['policy_version_id'],
            prompt_snapshot={'published_version_id': pin['policy_version_id']},
            input_snapshot={'message_id': inbound.id, PIN_KEY: pin,
                            'runtime_lane': 'isolated_simulation'},
            output_snapshot={})
        db.add(run)
        db.flush()
        inbound.metadata_json = {**(inbound.metadata_json or {}), PIN_KEY: pin,
            'agent_turn_status': 'processing', 'hermes_staged': True}
    run_id, inbound_id = run.id, inbound.id
    db.commit()  # reserve event and exact policy before any model request
    return run_id, inbound_id, pin


def _safe_observations(items):
    """Do not copy tool arguments/results, raw prompt or model history to traces."""
    from .tool_schemas import SCHEMAS
    out = []
    for item in (items or [])[-50:]:
        if not isinstance(item, dict) or item.get('tool') not in SCHEMAS:
            continue
        status = item.get('status')
        if status not in {'executed', 'rejected'}:
            continue
        error = item.get('error_code')
        out.append({'tool': item['tool'], 'status': status,
            'error_code': error if isinstance(error, str) and re.fullmatch(r'[A-Z0-9_]{1,80}', error) else None})
    return out


def _complete(db, run, inbound, output, revision, observations):
    # This runs inside the P08 state/visible reply transaction. Never create
    # a provider outbound record or claim an executed commercial effect.
    output.metadata_json = {**(output.metadata_json or {}), 'agent_run_id': run.id,
        'runtime_lane': 'isolated_simulation'}
    run.status = 'completed'
    run.error_code = None
    run.completed_at = _now()
    run.output_snapshot = {'reply': output.content, 'intent': 'lead_message',
        'proposed_actions': [], 'metadata': {'engine': 'hermes', 'runtime_lane': 'isolated_simulation',
            'message_id': output.id, 'delivery': 'in_app_only', 'state_revision': revision},
        'tool_observations': observations}
    inbound.metadata_json = {**(inbound.metadata_json or {}), 'agent_turn_status': 'answered',
                            'handled_by_message_id': output.id, 'agent_turn_error': None}
    db.flush()


def _mark_failed(db, scope, run_id, inbound_id):
    from app.modules.sales_agent.models import AgentRun, SalesMessage
    try:
        _lock_conversation(db, scope)
        run = db.query(AgentRun).filter_by(id=run_id).populate_existing().one_or_none()
        inbound = db.get(SalesMessage, inbound_id)
        # Another execution may already have committed while this one failed.
        if run and run.status != 'completed' and inbound:
            run.status = 'failed'
            run.error_code = 'HERMES_STAGED_TURN_FAILED'
            run.completed_at = _now()
            inbound.metadata_json = {**(inbound.metadata_json or {}), 'agent_turn_status': 'failed',
                'agent_turn_error': 'Isolated Hermes turn failed; inspect the worker.'}
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()  # never mask the original exception


def execute_isolated_turn(db, scope: TurnScope, *, inbound_message_id: str | None = None,
                          event_id: str | None = None, message: str | None = None):
    """Real SDK via P08, on explicitly isolated DB only; not a production route.

    Exactly one of persisted inbound ID or new event+message is required. A
    retry reuses the durable event/policy. The same AgentRun is committed with
    the visible message and Hermes state receipt, not after provider delivery.
    """
    from app.modules.sales_agent.models import AgentRun, SalesMessage
    from .bp_p04_turn import commit_p04_simulation_receipt
    from .p08_simulation import execute_staged_simulation, _replies, _existing_receipt
    from .staff_config import snapshot

    require_staging_database(db)
    if (inbound_message_id is not None) == (event_id is not None or message is not None):
        raise ValueError('Pass an inbound ID or a new event ID and message, not both.')
    run_id = inbound_id = None
    try:
        run_id, inbound_id, pin = _reserve(db, scope, inbound_message_id=inbound_message_id,
                                          event_id=event_id, message=message)
        conversation = _lock_conversation(db, scope)
        inbound = _validate_inbound(db, scope, conversation, inbound_id)
        run = db.query(AgentRun).filter_by(id=run_id).populate_existing().one()
        if ((inbound.metadata_json or {}).get(PIN_KEY) != pin or
                (run.input_snapshot or {}).get(PIN_KEY) != pin or
                run.prompt_configuration_id != pin['policy_version_id']):
            raise StagedRuntimeError('The event pin changed before execution.')
        policy = _policy(db, pin['policy_version_id'])
        replies = _replies(db, scope, inbound_id)
        receipt = _existing_receipt(db, scope, inbound_id)
        if replies or receipt:
            # Replay only when all three durable records agree. Do not require
            # model credentials to inspect an already completed exact receipt.
            if (len(replies) != 1 or receipt is None or run.status != 'completed' or
                    (replies[0].metadata_json or {}).get('hermes_version_id') != pin['policy_version_id'] or
                    (replies[0].metadata_json or {}).get('agent_run_id') != run_id or
                    (run.output_snapshot or {}).get('reply') != replies[0].content or
                    (run.output_snapshot or {}).get('metadata', {}).get('message_id') != replies[0].id):
                raise StagedRuntimeError('Inconsistent staged receipt; staff review required.')
            def no_prepare(*args, **kwargs):
                raise StagedRuntimeError('Replay must never invoke the SDK.')
            result = execute_staged_simulation(db, scope, inbound_message_id=inbound_id,
                settings=None, enabled_tools=frozenset(), published_version_id=pin['policy_version_id'],
                prepare=no_prepare)
            result['state_revision'] = receipt.revision
            db.commit()
        else:
            if run.status == 'completed':
                raise StagedRuntimeError('Completed run has lost its receipt.')
            if not snapshot(db)['configuration'].get('enabled'):
                raise StagedRuntimeError('Current Hermes configuration is disabled.')
            settings = HermesSettings(api_key=os.environ.get('OPENROUTER_API_KEY', ''),
                model=policy.model, max_iterations=policy.max_iterations, prompt=policy.system_prompt)
            run.status = 'running'
            run.error_code = None
            run.completed_at = None
            def commit_with_run(session, prepared, *, outbound_message_id):
                committed = commit_p04_simulation_receipt(session, prepared, outbound_message_id=outbound_message_id)
                output = session.get(SalesMessage, outbound_message_id)
                observations = _safe_observations(prepared.prepared.result.tool_observations)
                _complete(session, run, inbound, output, committed.revision, observations)
                return committed
            result = execute_staged_simulation(db, scope, inbound_message_id=inbound_id,
                settings=settings, enabled_tools=frozenset(policy.enabled_tools),
                published_version_id=pin['policy_version_id'], commit=commit_with_run)
            if result.get('replayed'):
                # Locks serialize this path, so a replay here indicates a
                # writer outside HEI-01B and must not be attributed to it.
                raise StagedRuntimeError('Unexpected staged replay; staff review required.')
        return {**result, 'engine': 'hermes', 'engine_version': ENGINE_VERSION,
                'event_id': pin['event_id'], 'run_id': run_id, 'inbound_message_id': inbound_id}
    except Exception:
        db.rollback()
        if run_id is not None:
            _mark_failed(db, scope, run_id, inbound_id)
        raise
