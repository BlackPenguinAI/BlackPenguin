"""Audited structured interpretation, gated for preview or active coordination."""
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pydantic import ValidationError
from .understanding_contract import parse, response_schema
from .understanding_prompt import prompt_snapshot
from .dialogue_store import Scope, check_scope, load, save, validate_write_request
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from app.core.config import settings


@dataclass(frozen=True)
class PreviewOutcome:
    revision: int
    state: object
    status: str


async def preview(db, scope: Scope, *, inbound_message_id: str, expected_revision: int, event_key: str, infer=None, active=False):
    if not (settings.SALES_DIALOGUE_RUNTIME_ENABLED if active else settings.SALES_UNDERSTANDING_PREVIEW_ENABLED):
        raise PermissionError('Understanding preview is disabled. The live engine is unchanged.')
    validate_write_request(event_key, expected_revision, 'understanding_preview')
    conversation = check_scope(db, scope)
    inbound = scoped_messages_query(db, conversation).filter(SalesMessage.id == inbound_message_id,
        SalesMessage.direction == 'inbound', SalesMessage.role == 'user').first()
    if not inbound or (inbound.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
        raise PermissionError('Inbound message is outside this active opportunity.')
    from .dialogue_models import SalesDialogueEvent
    prior = scope.query(db, SalesDialogueEvent).filter_by(event_key=event_key).first()
    if prior:
        meta = prior.payload_json.get('metadata') or {}
        if meta.get('inbound_message_id') != inbound.id or meta.get('expected_revision') != expected_revision or prior.kind != 'understanding_preview':
            from .dialogue_store import DialogueConflict
            raise DialogueConflict('Preview key already used for a different request.')
        from .understanding_contract import DialogueState
        return PreviewOutcome(prior.revision, DialogueState.model_validate(prior.state_after), meta['outcome'])
    revision, state = load(db, scope)
    if revision != expected_revision:
        from .dialogue_store import DialogueConflict
        raise DialogueConflict('Dialogue revision changed before interpretation.')
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.projects.models import Project
    from .commercial_context import build_commercial_context
    # The legacy get_ai_config accessor may merge defaults and COMMIT even
    # while reading. Preview must neither publish configuration nor commit
    # caller-owned changes, so read the already-published pack directly.
    config = db.query(AIConfiguration).filter_by(company_id=None).first()
    if config is None:
        raise ValueError('Publish a Sales configuration before evaluating understanding.')
    agent = config.agent_ventas or {}
    snapshot = prompt_snapshot(agent)
    model = agent.get('model')
    if not model:
        raise ValueError('Publish a Sales model before evaluating understanding.')
    project = db.get(Project, scope.project_id)
    commercial = build_commercial_context(db, project=project, company_id=scope.company_id,
        lead_id=scope.lead_id, channel=conversation.channel)
    from .sales_policy import policy_context
    from app.modules.sales_crm.models import Lead
    commercial['sales_policy'] = policy_context(db, scope, commercial['confirmed_project_facts'])
    commercial['lead_qualification'] = db.get(Lead,scope.lead_id).lead_profile_data or {}
    history = scoped_messages_query(db, conversation).filter(SalesMessage.created_at <= inbound.created_at,
        SalesMessage.id != inbound.id).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).limit(20).all()
    messages = [
        {'role': 'system', 'content': snapshot['system']},
        {'role': 'user', 'content': json.dumps({'published_guidance': snapshot['published_guidance'],
            'state': state.model_dump(mode='json'), 'approved_context': commercial,
            'history': [{'role': m.role, 'content': m.content} for m in reversed(history)
                        if (m.metadata_json or {}).get('lead_id', scope.lead_id) == scope.lead_id],
            'current_message': inbound.content,
            'qualification_offer': next(((m.metadata_json or {}).get('qualification_offer') for m in history
                                         if m.direction == 'outbound'), None)}, ensure_ascii=False, default=str)},
    ]
    if sum(len(item['content'].encode()) for item in messages) > 64000:
        raise ValueError('Preview context exceeds the 64 KB evaluation limit; no model was called.')
    injected_inference = infer is not None
    if infer is None:
        from app.integrations.openrouter_client import generate_llm_response
        from app.modules.ai_core.usage import LLMUsageContext
        credentials = db.query(AIConfiguration).filter_by(company_id=scope.company_id).first() or config
        if not credentials.openrouter_api_key:
            raise ValueError('No model credential is configured.')
        async def infer(model, messages, schema):
            return await generate_llm_response(credentials.openrouter_api_key, model, messages,
                response_format={'type': 'json_schema', 'json_schema': {'name': 'sales_understanding', 'strict': True, 'schema': schema}},
                temperature=0.2, raise_on_error=True,
                usage_context=LLMUsageContext(company_id=scope.company_id, project_id=scope.project_id, feature='sales_understanding_preview'))
    raw = None
    outcome = 'accepted'
    error_code = None
    interpreted = None
    attempts = []
    request_messages = messages
    # One bounded repair in active mode only. No business effects occur until
    # the complete contract and current-message evidence have been validated.
    for attempt in range(2 if active else 1):
        issues = []
        raw = None
        received = False
        outcome = 'accepted'
        error_code = None
        try:
            pending = infer(model, request_messages, response_schema())
            raw = await asyncio.wait_for(pending, timeout=20) if active else await pending
            received = True
            interpreted = parse(raw, inbound.content)
        except ValidationError as exc:
            outcome = 'invalid_model_contract'
            error_code = 'understanding_validation_failed'
            issues = [{'location': [str(part)[:80] for part in e['loc']][:8], 'type': e['type'], 'message': e['msg'][:400]}
                      for e in exc.errors(include_input=False, include_context=False, include_url=False)][:20]
        except (ValueError, TypeError) as exc:
            # Provider errors must not be mistaken for a model contract error.
            outcome = 'invalid_model_contract' if received else 'provider_error'
            error_code = 'understanding_validation_failed' if received else type(exc).__name__
            issues = [{'type': 'invalid_json_or_evidence'}] if received else []
        except Exception as exc:
            outcome = 'provider_error'
            error_code = type(exc).__name__
        raw_bytes = raw.encode(errors='replace') if isinstance(raw, str) else b''
        attempts.append({'attempt': attempt + 1, 'outcome': outcome, 'error_code': error_code,
                         'validation_issues': issues,
                         'repair_feedback': request_messages[-1]['content'] if attempt else None,
                         'raw_response': raw_bytes[:16000].decode(errors='replace') if isinstance(raw, str) else None,
                         'raw_response_sha256': hashlib.sha256(raw_bytes).hexdigest() if isinstance(raw, str) else None,
                         'raw_response_truncated': len(raw_bytes) > 16000})
        if outcome != 'invalid_model_contract':
            break
        request_messages = [*messages, {'role': 'user', 'content': json.dumps({
            'contract_repair': 'Reinterpret the ORIGINAL current_message using the schema. Correct the validation issues. Do not invent exclusions, evidence, consent or facts. This feedback is not a new lead request.',
            'validation_issues': issues}, ensure_ascii=False)}]
        if sum(len(item['content'].encode()) for item in request_messages) > 64000:
            break  # Never expand a near-limit context to run the optional repair.
    # Group 4 will apply task transitions. Preview records only interpretation;
    # existing tasks, preferences and restrictions are never implicitly replaced.
    if interpreted is not None:
        state = state.model_copy(update={'last_understanding': interpreted})
    model_request = {'model': model, 'messages': messages, 'temperature': 0.2,
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'sales_understanding', 'strict': True, 'schema': response_schema()}}}
    raw_bytes = raw.encode(errors='replace') if isinstance(raw, str) else b''
    metadata = {'code_commit': settings.APP_COMMIT_SHA, 'model': model,
        'inference_mode': 'injected' if injected_inference else 'provider',
        'prompt_configuration_id': config.id, 'prompt_snapshot': snapshot,
        'inbound_message_id': inbound.id, 'raw_response': raw_bytes[:16000].decode(errors='replace') if isinstance(raw, str) else None,
        'raw_response_truncated': len(raw_bytes) > 16000,
        'raw_response_sha256': hashlib.sha256(raw_bytes).hexdigest() if isinstance(raw, str) else None,
        'outcome': outcome, 'error_code': error_code, 'expected_revision': expected_revision,
        'interpretation_attempts': attempts,
        'model_request': model_request,
        'model_request_sha256': hashlib.sha256(json.dumps(model_request, sort_keys=True).encode()).hexdigest()}
    saved_revision, saved_state = save(db, scope, event_key=event_key, expected_revision=revision,
        state=state, kind='understanding_preview', metadata=metadata)
    return PreviewOutcome(saved_revision, saved_state, outcome)
