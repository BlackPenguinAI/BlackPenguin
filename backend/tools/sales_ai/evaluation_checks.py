"""Machine-checkable assertions; LLM judgements never override these results."""
import json
import re
import traceback
from pathlib import Path


def error_details(exc):
    """Useful locations without exception bodies, SQL parameters or prompts."""
    result = {'error_code':type(exc).__name__, 'error_frames':[
        {'file':Path(frame.filename).name,'function':frame.name,'line':frame.lineno}
        for frame in traceback.extract_tb(exc.__traceback__)[-5:]]}
    response = getattr(exc,'response',None)
    status = getattr(response,'status_code',getattr(exc,'status_code',None))
    if type(status) is int and 100 <= status <= 599:result['http_status']=status
    return result


def check(name, passed, detail=''):
    return {'check': name, 'status': 'PASS' if passed else 'FAIL', 'detail': detail}


def turn_checks(run, reply, expected, profile, share_count, previous_reply=None, repeated_question=False):
    output = run.output_snapshot or {}
    metadata = output.get('metadata') or {}
    composition = metadata.get('composition') or {}
    understanding = (run.input_snapshot or {}).get('understanding') or {}
    findings = [check('current_workflow', output.get('workflow_version') == 'sales-current/1.0'),
                check('interpretation', not run.error_code, run.error_code or ''),
                check('reply_present', bool(reply.strip()))]
    if composition:
        findings.append(check('composition_accepted', composition.get('status') == 'accepted'))
    elif run.error_code:
        findings.append(check('composition_accepted', False, 'Interpretation failed before composition.'))
    if previous_reply and not repeated_question and reply.strip() == previous_reply.strip():
        findings.append(check('no_identical_consecutive_reply', False))
    current = profile.get('current') or {}
    if expected == 'budget':
        values = [current.get(k, {}).get('value') for k in ('budget','budget_minimum','budget_maximum')]
        texts = json.dumps(values).replace(',', '').lower()
        findings.append(check('budget_captured', bool(re.search(r'(?<![\d.])1500000(?:\.0+)?(?![\d.])',texts)
                                                     or re.search(r'\b1\.5\s*m(?:illion)?\b',texts))))
        currency = str(current.get('budget_currency', {}).get('value') or '')
        findings.append(check('budget_currency_captured', 'usd' in (texts + currency).lower()))
    if expected == 'cash':
        value = current.get('financing', {})
        cash = str(value.get('value')).lower()
        findings.append(check('cash_captured', value.get('status') == 'declared' and bool(re.search(r'\bcash\b',cash))
                              and not re.search(r'\b(?:no|not|without)\s+(?:any\s+)?cash\b',cash)))
    if expected == 'parking':
        requests = understanding.get('requests') or []
        findings.append(check('parking_not_inventory', bool(requests) and
                              all(r.get('topic') != 'inventory' for r in requests)))
    if expected == 'material':
        findings.append(check('material_share_issued_in_sandbox', share_count > 0))
    if expected == 'repair':
        findings.append(check('cash_context_retained_after_correction',
                              'cash' in str(current.get('financing',{}).get('value')).lower()))
    if expected == 'multiple':
        topics = {r.get('topic') for r in understanding.get('requests', [])}
        findings.append(check('property_question_preserved', bool(topics & {'catalog','property_details','amenities','general'})))
    if expected == 'stop':
        findings.append(check('opt_out_observed', output.get('intent') == 'opt_out' or
                              metadata.get('control_outcome') == 'opt_out'))
    return findings


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {k: sanitize(v, secrets) for k, v in value.items()
                if k not in {'openrouter_api_key','api_key','authorization','prompt_snapshot','model_request'}}
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret: value = value.replace(secret, '[REDACTED]')
        return re.sub(r'https?://[^\s]+/projects/a/[^\s]+', '[sandbox-material-link]', value)
    return value
