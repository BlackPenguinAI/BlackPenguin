"""Bounded persisted task/read loop shared by preview and active coordination."""
from dataclasses import dataclass
import hashlib
import json
import time
from app.core.config import settings
from .dialogue_store import load, save, check_scope, validate_write_request, DialogueConflict
from .dialogue_models import SalesDialogueEvent
from .understanding_contract import Understanding, DialogueState, ToolResult
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from .dialogue_tasks import prepare_tasks, resolve_reference, restricted, record_result
from .dialogue_tools import ReadTools, ToolCall


@dataclass(frozen=True)
class TurnOutcome:
    revision: int
    state: DialogueState
    results: tuple
    stop_reason: str


def run_turn(db, scope, *, message_id, understanding, expected_revision, event_key,
             max_steps=8, max_seconds=5.0, max_rounds=3,max_read_units=12,clock=time.monotonic):
    validate_write_request(event_key, expected_revision, 'state_update')
    if type(max_steps) is not int or not 1 <= max_steps <= 30 or type(max_seconds) not in {int,float} or not 0 < max_seconds <= 30:
        raise ValueError('Invalid runtime limits.')
    from .next_flow import selected
    if selected(scope):
        if type(max_rounds) is not int or not 1<=max_rounds<=6 or type(max_read_units) is not int or not 1<=max_read_units<=60:
            raise ValueError('Invalid planning limits.')
        from .turn_planner import run
        return run(db,scope,message_id=message_id,understanding=understanding,expected_revision=expected_revision,
            event_key=event_key,max_steps=max_steps,max_seconds=max_seconds,max_rounds=max_rounds,max_read_units=max_read_units,clock=clock)
    conversation = check_scope(db, scope)
    message = scoped_messages_query(db, conversation).filter_by(id=message_id, direction='inbound', role='user').first()
    if not message or (message.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
        raise PermissionError('Message is outside the active opportunity.')
    understanding = Understanding.model_validate(understanding.model_dump() if isinstance(understanding, Understanding) else understanding).check_evidence(message.content)
    fingerprint = hashlib.sha256(json.dumps({'message_id':message.id, 'understanding':understanding.model_dump(mode='json'),
        'expected_revision':expected_revision, 'max_steps':max_steps, 'max_seconds':max_seconds}, sort_keys=True).encode()).hexdigest()
    prior = scope.query(db, SalesDialogueEvent).filter_by(event_key=event_key).first()
    if prior:
        meta = prior.payload_json.get('metadata') or {}
        if meta.get('runtime_fingerprint') != fingerprint:
            raise DialogueConflict('Runtime event key reused for a different turn.')
        return TurnOutcome(prior.revision, DialogueState.model_validate(prior.state_after),
            tuple(ToolResult.model_validate(r) for r in meta['results']), meta['stop_reason'])
    revision, state = load(db, scope)
    if revision != expected_revision:
        raise DialogueConflict('Dialogue revision changed.')
    from .request_safety import apply_vetoes
    understanding=apply_vetoes(understanding,message.content)
    state = prepare_tasks(state, understanding, message.id)
    results, references = [], []
    reference_pending = False
    for reference in understanding.references:
        resolved = resolve_reference(db, scope, state, reference)
        references.append({'reference':reference.model_dump(), 'resolved':resolved})
        if resolved and resolved['kind'] == 'property':
            state.selected_property_type_id = resolved['id']
        if not resolved:
            reference_pending = True
    gateway = ReadTools(db, scope)
    started, attempts, stop = clock(), set(), 'finished'
    # Current needs first; interrupted tasks can resume when not explicitly held.
    ordered = sorted(state.tasks, key=lambda t:t.source_message_id != message.id)
    for _ in range(0 if understanding.requires_clarification else max_steps):
        if clock() - started >= max_seconds:
            stop = 'time_limit'; break
        eligible = [t for t in ordered if t.id not in attempts and t.status in {'pending','suspended'}
            and all(any(d.id == dep and d.status == 'completed' for d in state.tasks) for dep in t.depends_on)]
        if not eligible:
            break
        task = eligible[0]; attempts.add(task.id)
        if task.topic.value in {'property_details','materials','pricing','inventory','appointment'} and reference_pending:
            task.status = 'awaiting_user'; continue
        call = ToolCall(operation_id=task.id, task_id=task.id, topic=task.topic, subject=task.subject,
            property_id=(task.property_id or state.selected_property_type_id) if task.topic.value in {'property_details','materials','pricing','inventory'} else None)
        if task.source_message_id == message.id and task.topic.value in {'property_details','materials','pricing','inventory'}:
            task.property_id = call.property_id
        if restricted(state, task):
            result = ToolResult(operation_id=task.id, status='denied', safe_message='An explicit restriction blocks this task.')
        else:
            try:
                result = gateway.execute(call, state)
            except Exception as exc:
                result = ToolResult(operation_id=task.id, status='error', safe_message=type(exc).__name__)
        results.append(result)
        record_result(state, task, result)
    else:
        stop = 'clarification' if understanding.requires_clarification else 'step_limit'
    if stop == 'finished' and any(t.status in {'pending','blocked','suspended','awaiting_user'} for t in state.tasks):
        stop = 'needs_follow_up'
    # Outcome is a diagnostic proposal, not a delivery capability. Return the
    # same sanitized result on the first call and persisted audit retries.
    from .monitor import redact
    results = [ToolResult.model_validate(redact(r.model_dump(mode='json'))) for r in results]
    new_revision, state = save(db, scope, event_key=event_key, expected_revision=revision, state=state,
        metadata={'runtime_version':'sales-runtime/1.0', 'runtime_fingerprint':fingerprint, 'message_id':message.id,
                  'results':[r.model_dump(mode='json') for r in results], 'references':references, 'stop_reason':stop,
                  'external_actions':0})
    return TurnOutcome(new_revision, state, tuple(results), stop)
