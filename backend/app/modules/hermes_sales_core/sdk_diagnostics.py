"""HEI-07B.2 private, bounded failure evidence; no customer text or secrets."""
from __future__ import annotations
import json
import re
import traceback
from pathlib import PurePath

HEADER = 'X-Hermes-Failure'
BUSY_DETAIL = 'Hermes preparation is busy.'
REVIEW_DETAIL = 'Hermes preparation requires review.'


def _identifier(value, default='unknown'):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', value) else default


def evidence(exc, checkpoint):
    data = {'checkpoint': _identifier(checkpoint),
            'exception_type': _identifier(type(exc).__name__),
            'locations': [{'file': _identifier(PurePath(f.filename).name), 'line': f.lineno}
                          for f in traceback.extract_tb(exc.__traceback__)[-6:]]}
    sqlstate = getattr(getattr(exc, 'orig', None), 'pgcode', None) or getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if isinstance(sqlstate, str) and re.fullmatch(r'[A-Z0-9]{5}', sqlstate):
        data['sqlstate'] = sqlstate
    return data


def read_evidence(raw):
    """Treat remote diagnostics as untrusted; never propagate raw HTTP bodies."""
    if not isinstance(raw, str) or len(raw) > 2048:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {k: _identifier(data.get(k)) for k in ('checkpoint', 'exception_type')}
    locations = data.get('locations')
    result['locations'] = [{'file': _identifier(x.get('file')), 'line': x['line']}
                           for x in locations[:6] if isinstance(x, dict)
                           and type(x.get('line')) is int and 0 < x['line'] < 1000000] if isinstance(locations, list) else []
    if isinstance(data.get('sqlstate'), str) and re.fullmatch(r'[A-Z0-9]{5}', data['sqlstate']):
        result['sqlstate'] = data['sqlstate']
    return result


def response_failure(response):
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = {}
    detail = body.get('detail') if isinstance(body, dict) else None
    status = response.status_code
    # Only this exact branch guarantees the preparation lock was not acquired.
    busy = status == 409 and detail == BUSY_DETAIL
    code = ('SDK_BUSY' if busy else 'SDK_PREPARATION_REVIEW' if status == 409 else
            'SDK_AUTHORIZATION_FAILED' if status in (401, 403) else
            'SDK_NOT_READY' if status == 503 else 'SDK_HTTP_ERROR')
    data = {'sdk_http_status': status, 'sdk_error_code': code}
    if status == 409 and detail == REVIEW_DETAIL:
        remote = read_evidence(response.headers.get(HEADER))
        if remote:
            data['sdk_failure'] = remote
    return data
