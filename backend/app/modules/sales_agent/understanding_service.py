"""Audited structured interpretation, gated for preview or active coordination."""
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pydantic import ValidationError
from .understanding_contract import parse, decode, response_schema
from .evidence import EvidenceError
from .understanding_prompt import prompt_snapshot, TURN_RULES
from .dialogue_store import Scope, check_scope, load, save, validate_write_request
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from app.core.config import settings


@dataclass(frozen=True)
class PreviewOutcome:
    revision: int
    state: object
    status: str
    declarations: tuple = ()


async def _preview(db, scope: Scope, *, inbound_message_id: str, expected_revision: int, event_key: str, infer=None, active=False, audit=None):
    if not active and not settings.SALES_UNDERSTANDING_PREVIEW_ENABLED:
        raise PermissionError('Understanding preview is disabled. The live engine is unchanged.')
    validate_write_request(event_key, expected_revision, 'understanding_preview')
    conversation = check_scope(db, scope)
    inbound = scoped_messages_query(db, conversation).filter(SalesMessage.id == inbound_message_id,
        SalesMessage.direction == 'inbound', SalesMessage.role == 'user').first()
    if not inbound or (inbound.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
        raise PermissionError('Inbound message is outside this active opportunity.')
    audit=audit if audit is not None else {}
    from .dialogue_models import SalesDialogueEvent
    prior = scope.query(db, SalesDialogueEvent).filter_by(event_key=event_key).first()
    if prior:
        meta = prior.payload_json.get('metadata') or {}
        if meta.get('inbound_message_id') != inbound.id or meta.get('expected_revision') != expected_revision or prior.kind != 'understanding_preview':
            from .dialogue_store import DialogueConflict
            raise DialogueConflict('Preview key already used for a different request.')
        from .understanding_contract import DialogueState
        return PreviewOutcome(prior.revision, DialogueState.model_validate(prior.state_after), meta['outcome'],tuple(meta.get('validated_declarations') or ()))
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
    agent = config.agent_ventas or {} if config else {}
    snapshot = prompt_snapshot(agent)
    model = agent.get('model')
    from .next_flow import selected
    next_enabled=selected(scope)
    if next_enabled:
        from .turn_configuration import resolve
        from .understanding_prompt import next_prompt_snapshot
        guidance=resolve(db,scope)
        snapshot=next_prompt_snapshot(guidance)
        model=guidance['model']
        config=db.get(AIConfiguration,guidance['source']['configuration_id'])
    elif config is None:
        raise ValueError('Publish a Sales configuration before evaluating understanding.')
    if not model:
        raise ValueError('Publish a Sales model before evaluating understanding.')
    project = db.get(Project, scope.project_id)
    commercial = build_commercial_context(db, project=project, company_id=scope.company_id,
        lead_id=scope.lead_id, channel=conversation.channel)
    from .sales_policy import policy_context
    from app.modules.sales_crm.models import Lead
    commercial['sales_policy'] = policy_context(db, scope, commercial['confirmed_project_facts'])
    commercial['lead_qualification'] = db.get(Lead,scope.lead_id).lead_profile_data or {}
    turn_context=None
    if next_enabled:
        from .turn_memory import build
        turn_context=build(db,scope,inbound_message_id=inbound.id)
        commercial.pop('lead_qualification',None)
    history = scoped_messages_query(db, conversation).filter(SalesMessage.created_at <= inbound.created_at,
        SalesMessage.id != inbound.id).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).limit(20).all()
    context_history=turn_context.pop('history') if turn_context else None
    context_payload={'published_guidance': snapshot['published_guidance'],
        'state': state.model_dump(mode='json'), 'approved_context': commercial,
        'history': context_history if context_history is not None else [{'role':m.role,'content':m.content} for m in reversed(history)
            if (m.metadata_json or {}).get('lead_id',scope.lead_id)==scope.lead_id],
        'current_message':inbound.content,
        'qualification_offer':turn_context.get('qualification_offer') if turn_context else next(((m.metadata_json or {}).get('qualification_offer') for m in history if m.direction=='outbound'),None)}
    if turn_context:context_payload['turn_context']=turn_context
    if (inbound.metadata_json or {}).get('resume_context'):
        sources=[scoped_messages_query(db,conversation).filter_by(id=identifier,direction='inbound',role='user').one()
                 for identifier in inbound.metadata_json['source_message_ids']]
        context_payload['resume_sources']=[{'message_id':m.id,'content':m.content} for m in sources]
    if turn_context:
        # The backend retains the complete state. Avoid copying a growing audit
        # history into the model twice; this is a reference projection only.
        context_payload['state']={'version':state.version,'selected_property_type_id':state.selected_property_type_id,
            'selected_unit_id':state.selected_unit_id,'offers':[o.model_dump(mode='json') for o in state.offers]}
    wire_mode=next_enabled and infer is None
    if wire_mode:
        from .interpretation_input import SYSTEM,VERSION
        snapshot={**snapshot,'system':SYSTEM,'input_contract':VERSION}
    else:snapshot = {**snapshot, 'system': snapshot['system'] + TURN_RULES}
    messages = [
        {'role': 'system', 'content': snapshot['system']},
        {'role': 'user', 'content': json.dumps(context_payload,ensure_ascii=False,default=str)},
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
    audit.update(model=model,prompt_snapshot=snapshot,prompt_configuration_id=config.id,inbound_message_id=inbound.id)
    raw = None
    outcome = 'accepted'
    error_code = None
    interpreted = None
    attempts = []
    audit['interpretation_attempts']=attempts
    request_messages = messages
    if wire_mode:
        from .interpretation_input import schema
        request_schema=schema(inbound.content)
    else:request_schema=response_schema(inbound.content)
    preserved=[]
    validated_declarations=[]
    if wire_mode:
        from .current_declarations import extract
        validated_declarations=extract(inbound.content)
        audit['validated_declarations']=[p.model_dump(mode='json') for p in validated_declarations]
    # One bounded repair in active mode only. No business effects occur until
    # the complete contract and current-message evidence have been validated.
    for attempt in range(2 if active else 1):
        issues = []
        normalizations=[]
        raw = None
        interpreted = None
        received = False
        draft=None
        outcome = 'accepted'
        error_code = None
        try:
            pending = infer(model, request_messages, request_schema)
            raw = await asyncio.wait_for(pending, timeout=20) if active else await pending
            received = True
            audit['pending_raw_response']=raw.encode(errors='replace')[:16000].decode(errors='replace') if isinstance(raw,str) else None
            if wire_mode:
                from .interpretation_input import compile_input
                from .current_declarations import extract,merge
                declarations=extract(inbound.content,raw)
                by_key={p.key:p for p in validated_declarations}
                for p in declarations:by_key.setdefault(p.key,p)
                validated_declarations=list(by_key.values())
                audit['validated_declarations']=[p.model_dump(mode='json') for p in validated_declarations]
                draft,compiled_notes=compile_input(raw,inbound.content,historical_messages=[m.content for m in history if m.direction=='inbound' and m.role=='user'])
                normalizations.extend(compiled_notes)
                draft,declaration_notes=merge(draft,validated_declarations)
                normalizations.extend(declaration_notes)
            else:draft=decode(raw)
            if next_enabled and not injected_inference and attempt==0:
                from .understanding_repair import verified_preferences
                preserved=verified_preferences(draft,inbound.content)
            interpreted = parse(draft.model_dump_json(), inbound.content) if wire_mode else parse(raw, inbound.content)
            if attempt and preserved:
                from .understanding_repair import preserve_preferences
                interpreted,restored=preserve_preferences(interpreted,preserved)
                normalizations.extend(restored)
                interpreted.check_evidence(inbound.content)
            if next_enabled and not injected_inference:
                from .understanding_repair import omit_unrelated_financial_preferences
                latest=next((m for m in history if m.direction=='outbound'),None)
                interpreted,omitted_preferences=omit_unrelated_financial_preferences(interpreted,
                    appointment_confirmation=bool(latest and (latest.metadata_json or {}).get('booking_confirmation')))
                normalizations.extend(omitted_preferences)
                from .dialogue_continuity import normalize as normalize_continuity
                interpreted,continuity_notes=normalize_continuity(interpreted,inbound.content,state,latest)
                normalizations.extend(continuity_notes)
                from .interpretation_consistency import normalize as normalize_consistency
                interpreted,consistency_notes=normalize_consistency(interpreted,inbound.content,commercial,appointment_offer=(latest.metadata_json or {}).get('appointment_offer') if latest else None)
                normalizations.extend(consistency_notes)
                from .understanding_completeness import scoped_subjects,completeness_issues
                interpreted,subject_notes=scoped_subjects(interpreted,inbound.content,commercial)
                normalizations.extend(subject_notes)
                from .understanding_semantics import issues_for
                offer=(latest.metadata_json or {}).get('appointment_offer') if latest else None
                from .first_booking import contextual_public_selection as exact_public_selection
                issues=issues_for(interpreted,inbound.content,appointment_offer=bool(offer and not exact_public_selection(inbound.content,offer)))
                from .understanding_repair import omit_declaration_questions
                interpreted,omitted=omit_declaration_questions(interpreted,issues)
                if omitted:
                    normalizations.extend(omitted)
                    issues=issues_for(interpreted,inbound.content,appointment_offer=bool(offer and not exact_public_selection(inbound.content,offer)))
                issues.extend(completeness_issues(interpreted,inbound.content))
                optional=[issue for issue in issues if issue['type'] in {'neutral_refusal_as_frustration','neutral_courtesy_as_emotion'}]
                if optional:
                    interpreted=interpreted.model_copy(update={'empathy':None})
                    normalizations.extend({'field':'empathy','action':'omit_unsupported_optional_affect','reason':issue['type']} for issue in optional)
                    issues=[issue for issue in issues if issue not in optional]
                if issues:raise EvidenceError(issues)
            if (inbound.metadata_json or {}).get('resume_context'):
                from .evidence import quotations
                issues=[{'location':path,'type':'evidence_mismatch','message':'Quote one original pending message; never join evidence across messages.'}
                        for item,key,path in quotations(interpreted.model_dump(mode='json')) if not any(item[key] in m.content for m in sources)]
                if issues:raise EvidenceError(issues)
        except EvidenceError as exc:
            outcome = 'invalid_model_contract'
            error_code = 'understanding_validation_failed'
            issues = list(exc.issues)
            if next_enabled and not injected_inference and draft is not None:
                from .understanding_semantics import issues_for
                for issue in issues_for(draft,inbound.content):
                    if issue not in issues:issues.append(issue)
        except ValidationError as exc:
            outcome = 'invalid_model_contract'
            error_code = 'understanding_validation_failed'
            issues = [{'location': [str(part)[:80] for part in e['loc']][:8], 'type': e['type'], 'message': e['msg'][:400]}
                      for e in exc.errors(include_input=False, include_context=False, include_url=False)][:20]
        except (ValueError, TypeError) as exc:
            # Provider errors must not be mistaken for a model contract error.
            outcome = 'invalid_model_contract' if received else 'provider_error'
            error_code = 'understanding_validation_failed' if received else type(exc).__name__
            issues = [{'location':[], 'type':'invalid_json' if isinstance(exc,json.JSONDecodeError) else 'contract_value_error',
                       'message':str(exc)[:400] if received and type(exc) is ValueError else 'Invalid JSON or contract value.'}] if received else []
        except Exception as exc:
            outcome = 'provider_error'
            error_code = type(exc).__name__
        raw_bytes = raw.encode(errors='replace') if isinstance(raw, str) else b''
        attempts.append({'attempt': attempt + 1, 'outcome': outcome, 'error_code': error_code,
                         'validation_issues': issues, 'normalizations':normalizations,
                         'quotation_schema':'source_enum' if any(row.get('properties',{}).get('evidence',{}).get('enum') for row in request_schema.get('$defs',{}).values()) else 'standard',
                         'repair_feedback': request_messages[-1]['content'] if attempt else None,
                         'raw_response': raw_bytes[:16000].decode(errors='replace') if isinstance(raw, str) else None,
                         'raw_response_sha256': hashlib.sha256(raw_bytes).hexdigest() if isinstance(raw, str) else None,
                         'raw_response_truncated': len(raw_bytes) > 16000})
        if outcome != 'invalid_model_contract':
            break
        from .understanding_repair import constrained_repair_schema,evidence_choices
        request_schema=constrained_repair_schema(schema(inbound.content) if wire_mode else response_schema(inbound.content),inbound.content,raw)
        request_messages = [*messages, {'role': 'user', 'content': json.dumps({
            'contract_repair': 'Reinterpret the ORIGINAL current_message using the schema. Correct the validation issues. Do not invent exclusions, evidence, consent or facts. This feedback is not a new lead request.',
            'validation_issues': issues, 'current_message': inbound.content,
            'allowed_request_and_preference_quotes':evidence_choices(inbound.content,raw),
            'verified_declarations_to_preserve':[p.model_dump(mode='json') for p in preserved],
            'repair_scope':'Choose exact source quotes from the schema enum for requests and preferences. Correct only failed fields and their necessary links; preserve valid declarations, visit timing and independent current questions.',
            'local_reference_rule': ('Use inline target objects and nested comparison members. Never output IDs or reference links; the backend generates them.' if wire_mode else 'Define local references such as ref1 and link only those, or use null. Database IDs are never interpretation reference IDs.'),
            'current_turn_rule': 'Do not replay historical questions. Budget and payment declarations belong in preferences, not requests. Preserve independent current questions.',
            'exact_short_quote': inbound.content if len(inbound.content) <= 2000 else None,
            'quotation_rule': 'Do not append punctuation. Meaning may be normalized in value/expression, but evidence must be copied verbatim from current_message. Keep independent requests and negations.'}, ensure_ascii=False)}]
        if sum(len(item['content'].encode()) for item in request_messages) > 64000:
            break  # Never expand a near-limit context to run the optional repair.
    # Group 4 will apply task transitions. Preview records only interpretation;
    # existing tasks, preferences and restrictions are never implicitly replaced.
    if outcome == 'accepted' and interpreted is not None:
        state = state.model_copy(update={'last_understanding': interpreted})
    model_request = {'model': model, 'messages': messages, 'temperature': 0.2,
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'sales_understanding', 'strict': True, 'schema': schema(inbound.content) if wire_mode else response_schema(inbound.content)}}}
    raw_bytes = raw.encode(errors='replace') if isinstance(raw, str) else b''
    metadata = {'code_commit': settings.APP_COMMIT_SHA, 'model': model,
        'inference_mode': 'injected' if injected_inference else 'provider',
        'prompt_configuration_id': config.id, 'prompt_snapshot': snapshot,
        'inbound_message_id': inbound.id, 'raw_response': raw_bytes[:16000].decode(errors='replace') if isinstance(raw, str) else None,
        'raw_response_truncated': len(raw_bytes) > 16000,
        'raw_response_sha256': hashlib.sha256(raw_bytes).hexdigest() if isinstance(raw, str) else None,
        'outcome': outcome, 'error_code': error_code, 'expected_revision': expected_revision,
        'interpretation_attempts': attempts,
        'validated_declarations':[p.model_dump(mode='json') for p in validated_declarations],
        'input_contract':VERSION if wire_mode else 'sales-understanding/1.0',
        'model_request': model_request,
        'model_request_sha256': hashlib.sha256(json.dumps(model_request, sort_keys=True).encode()).hexdigest()}
    if 'configuration_ref' in snapshot:
        metadata['configuration_ref']=snapshot['configuration_ref']
        metadata['playbook_selection']=snapshot['published_guidance']['selection']
        metadata['turn_context_version']=turn_context['version'] if turn_context else None
        metadata['turn_context_sha256']=hashlib.sha256(json.dumps(turn_context,sort_keys=True,default=str).encode()).hexdigest()
    saved_revision, saved_state = save(db, scope, event_key=event_key, expected_revision=revision,
        state=state, kind='understanding_preview', metadata=metadata)
    return PreviewOutcome(saved_revision, saved_state, outcome,tuple(p.model_dump(mode='json') for p in validated_declarations))


async def preview(db,scope,*,inbound_message_id,expected_revision,event_key,infer=None,active=False):
    """Retain the attempt journal even when an unexpected later phase crashes."""
    audit={}
    try:
        return await _preview(db,scope,inbound_message_id=inbound_message_id,expected_revision=expected_revision,event_key=event_key,infer=infer,active=active,audit=audit)
    except Exception as exc:
        # Do not serialize the exception body: it may contain SQL or credentials.
        from .runtime_errors import diagnostic
        audit['error_diagnostic']=diagnostic(exc)
        exc.sales_interpretation_audit=audit
        raise
