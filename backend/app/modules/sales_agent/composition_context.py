"""P1-B.3: evidence-preserving model projection for structured composition.

Only the already-validated evidence blocks/continuations can be rendered.
Full source data and dialogue state remain untouched in the backend. This
projection never authorizes a read, changes a task, or modifies a receipt.
"""
import copy
import json

VERSION = 'sales-composition-context/1.0'
EXPECTED_FIELDS = frozenset({
    'version', 'published_guidance', 'current_message', 'turn_context',
    'validated_results', 'planning', 'evidence_blocks', 'continuations', 'style',
})
# Preserve all fields that can affect the permitted output or its context.
PLANNING_FIELDS = frozenset({
    'request_coverage', 'questions', 'pending_topics', 'deferred_requests',
    'write_candidates_require_backend_authorization',
})
# Exact known planner keys. Unknown additions preserve the full input until
# their semantics are reviewed (the same rule used for top-level fields).
PLANNING_KNOWN = PLANNING_FIELDS | frozenset({
    'version', 'references', 'rounds', 'read_units', 'tool_calls',
    'additional_model_calls', 'external_actions', 'limits', 'retired_tasks',
    'interest_reference', 'resumed_requests', 'context_sha256',
    'original_interest',
})
RESULT_KNOWN = frozenset({'version', 'operation_id', 'status', 'safe_message',
                          'evidence_ids', 'data'})
HISTORY_LIMIT = 8


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode('utf-8'))


def project(payload):
    """Produce an auditable, smaller LLM input; fail open to legacy *context*.

    A future/unknown payload schema is kept intact rather than silently losing
    any newly introduced semantic field. This is NOT an authorization fallback:
    backend tools, scope, policy and composition schema stay unchanged.
    """
    before = _bytes(payload)
    trace = {'version': VERSION, 'before_bytes': before, 'after_bytes': before,
             'saved_bytes': 0, 'history_messages_omitted': 0,
             'mode': 'preserved_unknown_contract'}
    if (not isinstance(payload, dict) or set(payload) != EXPECTED_FIELDS
            or not isinstance(payload.get('turn_context'), dict)
            or not isinstance(payload.get('planning'), dict)
            or not isinstance(payload.get('validated_results'), list)
            or not isinstance(payload.get('evidence_blocks'), list)
            or not isinstance(payload.get('continuations'), list)):
        return copy.deepcopy(payload), trace
    memory = payload['turn_context']
    history = memory.get('history')
    if (not isinstance(history, list)
            or any(not isinstance(item, dict) for item in history)
            or any(not isinstance(row, dict) or set(row)-RESULT_KNOWN
                   for row in payload['validated_results'])
            or set(payload['planning'])-PLANNING_KNOWN):
        return copy.deepcopy(payload), trace

    result = copy.deepcopy(payload)
    # Historical messages older than eight turns do not override persisted
    # restrictions, offers, proposals or recent context. Those authoritative
    # structures are all preserved, not summarized or truncated here.
    omit = max(0, len(history)-HISTORY_LIMIT)
    result['turn_context']['history'] = copy.deepcopy(history[-HISTORY_LIMIT:])
    # Full read data is already converted to immutable, authorized wordings in
    # evidence_blocks. The LLM only chooses those evidence IDs and continuations.
    # Keep read status and safe uncertainty, not the large catalog/tool payload.
    result['validated_results'] = [{k: copy.deepcopy(row[k]) for k in
                                    ('version', 'operation_id', 'status', 'safe_message') if k in row}
                                   for row in payload['validated_results']]
    # The planner has already executed and retains the full source for audit.
    # The composer needs unresolved questions and coverage, not resolver trees,
    # context digests or per-round tool receipts.
    result['planning'] = {k: copy.deepcopy(v) for k, v in payload['planning'].items()
                          if k in PLANNING_FIELDS}
    after = _bytes(result)
    if after >= before:
        return copy.deepcopy(payload), {**trace, 'mode': 'no_positive_reduction'}
    return result, {'version': VERSION, 'before_bytes': before,
                    'after_bytes': after, 'saved_bytes': before-after,
                    'history_messages_omitted': omit, 'mode': 'projected'}
