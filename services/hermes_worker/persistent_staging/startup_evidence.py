"""Allowlisted diagnostics for disposable, closed staging; never export exception text."""
import json
import re
import traceback
from pathlib import PurePath

PREFIX = 'HEI06A2_EVENT '
PHASES = frozenset({'environment','database_import','production_gate','database_identity','register_orm','bootstrap','api_import','api_schema','api_serve','api_lifespan','sdk_import','sdk_serve','health_http'})
STATUS = frozenset({'BEGIN','PASS','FAIL'})
REASONS = frozenset({'database_unavailable','schema_incompatible','http_error','connection_error','unexpected_response','startup_failed'})
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,79}\Z')
SAFE_FILE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}\.py\Z')


def event(phase, status, *, exc=None, reason=None, http_status=None):
    assert phase in PHASES and status in STATUS
    value={'phase':phase,'status':status}
    if exc is not None:
        name=type(exc).__name__
        value['exception_type']=name if IDENT.fullmatch(name) else 'UnknownError'
        frames=[]
        for f in traceback.extract_tb(exc.__traceback__):
            # Only application/staging frames, no absolute paths or source code.
            path=PurePath(f.filename)
            if ('app' in path.parts or 'stage' in path.parts or path.name in {'entrypoint.py','startup_evidence.py'}) and SAFE_FILE.fullmatch(path.name):
                frames.append({'file':path.name,'line':f.lineno})
        value['locations']=frames[-8:]
    if isinstance(reason,str) and reason in REASONS:value['reason']=reason
    if isinstance(http_status,int) and 100<=http_status<=599:value['http_status']=http_status
    print(PREFIX+json.dumps(value,sort_keys=True),flush=True)


def collect_events(raw):
    """Reconstruct allowlisted fields, never return the original log line."""
    result=[]
    for line in raw.splitlines():
        if not line.startswith(PREFIX):continue
        try:
            e=json.loads(line[len(PREFIX):])
            if not isinstance(e,dict) or e.get('phase') not in PHASES or e.get('status') not in STATUS:continue
            safe={'phase':e['phase'],'status':e['status']}
            if isinstance(e.get('exception_type'),str) and IDENT.fullmatch(e['exception_type']):safe['exception_type']=e['exception_type']
            if isinstance(e.get('reason'),str) and e['reason'] in REASONS:safe['reason']=e['reason']
            if type(e.get('http_status')) is int and 100<=e['http_status']<=599:safe['http_status']=e['http_status']
            if isinstance(e.get('locations'),list):
                safe['locations']=[{'file':x['file'],'line':x['line']} for x in e['locations'][-8:] if isinstance(x,dict) and isinstance(x.get('file'),str) and SAFE_FILE.fullmatch(x['file']) and type(x.get('line')) is int and 0<x['line']<100000]
            result.append(safe)
        except (ValueError,TypeError):continue
    return result[-50:]
