"""Safe failure locations for isolated tests; no raw traceback or failure text."""
from pathlib import Path
import json
import pytest

PROPERTY = 'hei06_offline_failure_v1'
FILES = frozenset({'test_harness_offline.py', 'test_focus_grounding.py',
    'test_candidate_postgres.py', 'test_staging_harness.py', 'test_staging_transport.py',
    'test_turn_lifecycle_harness.py', 'staging_scenarios.py', 'sdk_scenarios.py',
    'focus_grounding.py', 'staging_transport.py', 'live_service.py', 'live_preparation.py',
    'commercial_delivery.py', 'live_job.py', 'provider_delivery.py'})
TYPES = frozenset({'AssertionError', 'PermissionError', 'ProductionToolError',
    'HTTPException', 'ValueError', 'TypeError', 'KeyError', 'RuntimeError',
    'OperationalError', 'IntegrityError', 'HermesStateConflict', 'ReceiptPending'})
REASONS = {'Hermes delivery changed after preparation; review instead of sending.': 'dispatch_changed',
    'Reply requires monetary reconciliation before dispatch.': 'monetary_guard',
    'Reply requires language reconciliation before dispatch.': 'language_guard',
    'Explicit preference capture requires reconciliation.': 'preference_capture',
    'Explicit preference draft changed after inference.': 'preference_changed',
    'Verified visit selection requires reconciliation.': 'visit_selection_reconciliation'}


def clean(value):
    if not isinstance(value, dict):
        return None
    phase = value.get('phase')
    kind = value.get('type')
    reason = value.get('reason')
    if phase not in ('setup', 'call', 'teardown'):
        return None
    out = {'phase':phase, 'type':kind if isinstance(kind,str) and kind in TYPES else 'unknown',
           'reason':reason if isinstance(reason,str) and reason in REASONS.values() else 'unknown', 'locations':[]}
    locations = value.get('locations')
    if not isinstance(locations,list):
        return None
    for location in locations[-12:]:
        if not isinstance(location,dict):
            continue
        file, line = location.get('file'), location.get('line')
        if isinstance(file,str) and file in FILES and type(line) is int and 1<=line<=10000:
            out['locations'].append({'file':file,'line':line})
    return out


def failure_shape(exc, phase):
    locations=[]
    tb=exc.__traceback__
    while tb:
        file=Path(tb.tb_frame.f_code.co_filename).name
        if file in FILES:
            locations.append({'file':file,'line':tb.tb_lineno})
        tb=tb.tb_next
    return clean({'phase':phase,'type':type(exc).__name__,
                  'reason':REASONS.get(str(exc),'unknown'),'locations':locations})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome=yield
    report=outcome.get_result()
    if report.failed and call.excinfo is not None:
        record=failure_shape(call.excinfo.value,report.when)
        if record is not None:
            prop=(PROPERTY,json.dumps(record,separators=(',',':')))
            item.user_properties.append(prop)
            # Keep the property on this report as well as later teardown reports.
            if prop not in report.user_properties:
                report.user_properties.append(prop)


def parse_failures(case):
    out=[]
    for prop in case.findall('./properties/property'):
        if prop.get('name')!=PROPERTY:
            continue
        raw=prop.get('value','')
        if len(raw)>8192:
            continue
        try:
            record=clean(json.loads(raw))
        except (ValueError,TypeError):
            continue
        if record is not None and record not in out:
            out.append(record)
    return out[:3]
