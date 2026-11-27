"""Bounded, allowlisted diagnostics for synthetic HEI-06 tests only.

Do not export exception messages, tracebacks, model text, tool arguments,
provider responses, URLs, credentials, IDs or any other raw SDK output.
"""
from __future__ import annotations
import json
import re
from xml.etree import ElementTree as ET

PROPERTY = 'hei06_safe_trace_v1'
CASES = {
    f'test_{name}[repeat-{i}]': f'{alias}/repeat-{i}'
    for name, alias in [
        ('named_focus_pdf_followup_and_idempotency', 'focus_pdf'),
        ('numbered_menu_and_second_option', 'numbered_choice'),
    ] for i in (1, 2)
}
CHECKPOINTS = frozenset({
    'seed_catalog', 'named_details_turn', 'named_focus', 'named_details_tool',
    'named_reply_property', 'named_reply_bedrooms', 'implicit_pdf_turn',
    'pdf_focus', 'pdf_share', 'pdf_operation_receipt', 'pdf_media_tool',
    'pdf_outbound_link', 'pdf_replay', 'pdf_no_duplicate_delivery',
    'pdf_no_duplicate_inference', 'pdf_no_duplicate_share', 'stop_turn',
    'stop_no_inference', 'stop_opt_out', 'numbered_search_turn',
    'numbered_search_tool', 'numbered_menu_shape', 'numbered_menu_refs',
    'second_option_turn', 'second_option_focus', 'second_option_details_tool',
    'second_option_reply_property', 'second_option_reply_bathrooms',
    'second_option_run_count', 'complete',
})
TOOLS = frozenset({
    'search_properties', 'track_property_interest', 'get_project_overview',
    'evaluate_properties_for_lead', 'compare_properties', 'get_unit_details',
    'list_unit_assets', 'get_unit_media', 'get_available_visit_slots',
    'select_visit_time', 'book_onsite_visit', 'cancel_onsite_visit',
    'reschedule_onsite_visit', 'update_search_preferences', 'update_lead_profile',
    'unknown_tool',
})
TOOL_ERRORS = frozenset({
    'TOOL_ARGUMENT_INVALID', 'GLOBAL_TOOL_DISABLED', 'P01_EFFECTS_DISABLED',
    'DOMAIN_VALIDATION_REJECTED', 'TYPEERROR', 'VALUEERROR', 'KEYERROR',
    'PERMISSIONERROR', 'PROPERTY_NOT_FOUND_OR_AMBIGUOUS',
    'PROPERTY_REFERENCE_CONFLICT', 'MEDIA_TYPE_REQUIRED', 'PROPERTY_REQUIRED',
    'VISIT_CHOICE_AMBIGUOUS', 'LIVE_ACTION_NOT_CERTIFIED',
    'COMMERCIAL_POLICY_HOLD', 'VISIT_LOCATION_REQUIRED', 'unknown_error',
})
EXCEPTION_TYPES = frozenset({
    'AssertionError', 'ProductionToolError', 'RuntimeError', 'ValueError',
    'TypeError', 'KeyError', 'PermissionError', 'ImportError',
    'ModuleNotFoundError', 'HTTPException', 'HTTPStatusError', 'APITimeoutError',
    'APIConnectionError', 'APIStatusError', 'AuthenticationError',
    'PermissionDeniedError', 'RateLimitError', 'BadRequestError',
    'NotFoundError', 'InternalServerError', 'TimeoutError', 'OperationalError',
    'IntegrityError', 'HermesStateConflict', 'ReceiptPending', 'EngineUnavailable',
    'unknown_exception',
})
# Exact comparisons only. Never return or interpolate exception text.
EXACT_ERRORS = {
    'Reply requires monetary reconciliation before dispatch.': 'monetary_guard',
    'Reply requires language reconciliation before dispatch.': 'language_guard',
    'Concurrent commercial effects need separate turns.': 'concurrent_effects',
    'Commercial action policy requires review before live preparation.': 'commercial_hold',
    'Hermes did not provide a text response': 'empty_sdk_reply',
    'Hermes returned an unexpected response': 'invalid_sdk_response',
    'Hermes returned an invalid message history': 'invalid_sdk_history',
    'Pinned hermes-agent is required in the isolated runtime': 'sdk_import_failure',
    'Provider dispatcher returned no durable receipt.': 'missing_provider_receipt',
    'Final accepted reply missing.': 'missing_final_reply',
    'Final message has not been accepted.': 'final_reply_not_accepted',
    'Issued material plan requires review.': 'material_plan_review',
    'Existing live draft or receipt must be reconciled without model replay.': 'existing_draft_review',
    'Job was superseded while preparing.': 'superseded_job',
}
ERROR_REASONS = frozenset(EXACT_ERRORS.values()) | {'sdk_tool_allowlist_mismatch', 'unknown_reason'}
EVENTS = frozenset({'checkpoint', 'runtime_started', 'runtime_returned', 'runtime_error',
                    'prepare_started', 'prepare_returned', 'prepare_error',
                    'worker_started', 'worker_returned', 'worker_error', 'tool', 'reply_shape'})
MAX_EVENTS = 256
REPLY_FLAGS = frozenset({'van_buren', 'oakwood', 'three_bedrooms_plain', 'three_bedrooms_unformatted',
                         'two_bathrooms_plain', 'two_bathrooms_unformatted', 'share_path', 'question'})


def reply_shape(text, source):
    """Only fixed facts about the synthetic fixture; never return reply text."""
    if not isinstance(text, str):
        return {'event': 'reply_shape', 'source': source}
    text = text[:20000]
    plain = re.sub(r'[*_`]', '', text)
    return {'event': 'reply_shape', 'source': source,
            'van_buren': 'van buren' in text.casefold(), 'oakwood': 'oakwood' in text.casefold(),
            'three_bedrooms_plain': bool(re.search(r'\b(?:3|three)\s+bedrooms?\b', text, re.I)),
            'three_bedrooms_unformatted': bool(re.search(r'\b(?:3|three)\s+bedrooms?\b', plain, re.I)),
            'two_bathrooms_plain': bool(re.search(r'\b(?:2|two)\s+bathrooms?\b', text, re.I)),
            'two_bathrooms_unformatted': bool(re.search(r'\b(?:2|two)\s+bathrooms?\b', plain, re.I)),
            'numbered_lines': min(20, len(re.findall(r'^\s*[0-9]+[.)]\s+', plain, re.M))),
            'share_path': '/projects/a/' in text, 'question': '?' in text}


def allowed(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def clean_event(raw):
    """Project strictly; unknown keys are dropped, unknown enums are fixed labels."""
    if not isinstance(raw, dict) or not isinstance(raw.get('event'), str) or raw['event'] not in EVENTS:
        return None
    kind = raw['event']
    result = {'event': kind}
    if kind == 'checkpoint':
        result['code'] = allowed(raw.get('code'), CHECKPOINTS, 'unknown_checkpoint')
    elif kind.endswith('_error'):
        result['exception'] = allowed(raw.get('exception'), EXCEPTION_TYPES, 'unknown_exception')
        result['reason'] = allowed(raw.get('reason'), ERROR_REASONS, 'unknown_reason')
    elif kind == 'tool':
        result['tool'] = allowed(raw.get('tool'), TOOLS, 'unknown_tool')
        result['status'] = allowed(raw.get('status'), {'executed', 'rejected'}, 'unknown_status')
        error = raw.get('error_code')
        result['error_code'] = None if error is None else allowed(error, TOOL_ERRORS, 'unknown_error')
    elif kind == 'reply_shape':
        result['source'] = allowed(raw.get('source'), {'sdk', 'outbound'}, 'unknown_source')
        for flag in sorted(REPLY_FLAGS):
            if type(raw.get(flag)) is bool:
                result[flag] = raw[flag]
        count = raw.get('numbered_lines')
        if type(count) is int and 0 <= count <= 20:
            result['numbered_lines'] = count
    return result


class SafeTrace:
    def __init__(self):
        self.events = []
        self.truncated = False

    def add(self, event, **fields):
        item = clean_event({'event': event, **fields})
        if item is None:
            return
        if len(self.events) >= MAX_EVENTS:
            self.truncated = True
            return
        self.events.append(item)

    def checkpoint(self, code):
        self.add('checkpoint', code=code)

    def error(self, event, exc):
        reason = EXACT_ERRORS.get(str(exc), 'unknown_reason')
        if type(exc) is RuntimeError and str(exc).startswith('Hermes tool allowlist mismatch: '):
            reason = 'sdk_tool_allowlist_mismatch'
        self.add(event, exception=type(exc).__name__, reason=reason)

    def tools(self, observations):
        for item in (observations or [])[:50]:
            if isinstance(item, dict):
                self.add('tool', tool=item.get('tool'), status=item.get('status'), error_code=item.get('error_code'))

    def reply(self, text, source):
        self.add(**reply_shape(text, source))

    def serialized(self):
        return json.dumps({'events': self.events, 'truncated': self.truncated}, separators=(',', ':'))


def parse_trace(case):
    props = [p.get('value', '') for p in case.findall('./properties/property') if p.get('name') == PROPERTY]
    if len(props) != 1 or len(props[0]) > 65536:
        return [], 'MISSING_OR_INVALID'
    try:
        raw = json.loads(props[0])
        if not isinstance(raw, dict) or not isinstance(raw.get('events'), list) or len(raw['events']) > MAX_EVENTS:
            return [], 'MISSING_OR_INVALID'
        events = [clean_event(item) for item in raw['events']]
        if not events or any(item is None for item in events):
            return [], 'MISSING_OR_INVALID'
        return events, 'TRUNCATED' if raw.get('truncated') is True else 'RECORDED'
    except (ValueError, TypeError):
        return [], 'MISSING_OR_INVALID'


def case_details(path):
    """Export known case identities and safe events; never JUnit failure text."""
    result = {'schema': 'hei06-case-diagnostics/1', 'cases': [], 'unknown_cases': 0,
              'missing_cases': [], 'duplicate_cases': 0, 'complete': False}
    if not path.exists():
        result['missing_cases'] = sorted(CASES.values())
        return result
    seen = set()
    for case in ET.parse(path).iter('testcase'):
        alias = CASES.get(case.get('name'))
        if alias is None:
            result['unknown_cases'] += 1
            continue
        if alias in seen:
            result['duplicate_cases'] += 1
            continue
        seen.add(alias)
        status = 'FAIL' if case.find('failure') is not None or case.find('error') is not None else 'SKIP' if case.find('skipped') is not None else 'PASS'
        events, trace_status = parse_trace(case)
        checks = [event['code'] for event in events if event['event'] == 'checkpoint']
        result['cases'].append({'case': alias, 'status': status, 'trace_status': trace_status,
                                'last_checkpoint': checks[-1] if checks else None, 'events': events})
    result['missing_cases'] = sorted(set(CASES.values()) - seen)
    result['complete'] = (not result['missing_cases'] and not result['unknown_cases'] and
                          not result['duplicate_cases'] and all(
                              c['trace_status'] == 'RECORDED' and
                              (c['status'] != 'PASS' or c['last_checkpoint'] == 'complete')
                              for c in result['cases']))
    return result
