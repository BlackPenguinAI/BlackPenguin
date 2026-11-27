"""No SDK or provider dependency: exercise sanitized evidence export."""
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from diagnostics import CASES, MAX_EVENTS, PROPERTY, SafeTrace, case_details, clean_event, reply_shape
from run_lane import counts


def add_case(root, name, *, fail=False, trace=None):
    case = ET.SubElement(root, 'testcase', {'name': name, 'classname': 'secret-url-not-exported'})
    if fail:
        ET.SubElement(case, 'failure', {'message': 'PRIVATE-KEY-TEST'}).text = 'PRIVATE-KEY-TEST'
    if trace is not None:
        ET.SubElement(ET.SubElement(case, 'properties'), 'property', {'name': PROPERTY, 'value': trace})
    return case


def test_redacts_arbitrary_values_and_exception_text():
    t = SafeTrace()
    t.checkpoint('private-token')
    t.error('prepare_error', RuntimeError('https://secret.invalid/?key=PRIVATE-KEY-TEST'))
    t.tools([{'tool':'PRIVATE-KEY-TEST','status':'secret-url','error_code':'PRIVATE-KEY-TEST','arguments':{'key':'PRIVATE-KEY-TEST'}},
             {'tool':'get_unit_media','status':'rejected','error_code':'MEDIA_TYPE_REQUIRED'}])
    t.reply('Van Buren has **3** bedrooms. https://secret.invalid/projects/a/PRIVATE-KEY-TEST','sdk')
    raw = t.serialized()
    assert all(s not in raw for s in ('PRIVATE-KEY-TEST', 'secret.invalid', 'private-token', 'secret-url'))
    assert t.events[1]['reason'] == 'unknown_reason'
    assert t.events[3]['error_code'] == 'MEDIA_TYPE_REQUIRED'
    assert t.events[-1]['three_bedrooms_unformatted'] and not t.events[-1]['three_bedrooms_plain']
    assert t.events[-1]['share_path']


def test_classifies_known_guards_without_exception_text():
    t=SafeTrace()
    t.error('prepare_error', ValueError('Reply requires monetary reconciliation before dispatch.'))
    t.error('runtime_error', RuntimeError('Hermes tool allowlist mismatch: PRIVATE-KEY-TEST'))
    assert [e['reason'] for e in t.events] == ['monetary_guard','sdk_tool_allowlist_mismatch']
    assert 'PRIVATE-KEY-TEST' not in t.serialized()


def test_case_status_checkpoint_and_trace_are_exported(tmp_path):
    p=tmp_path/'report.xml';root=ET.Element('testsuite')
    for i,name in enumerate(CASES):
        t=SafeTrace();t.checkpoint('numbered_menu_shape' if i==0 else 'complete')
        add_case(root,name,fail=i==0,trace=t.serialized())
    ET.ElementTree(root).write(p)
    report=case_details(p)
    assert report['complete'] and len(report['cases'])==4
    assert report['cases'][0]['status']=='FAIL' and report['cases'][0]['last_checkpoint']=='numbered_menu_shape'
    assert counts(p)['passed']==3 and counts(p)['failed']==1
    assert 'PRIVATE-KEY-TEST' not in json.dumps(report)
    assert 'secret-url-not-exported' not in json.dumps(report)


def test_unknown_duplicate_and_missing_cases_are_not_certified(tmp_path):
    p=tmp_path/'report.xml';root=ET.Element('testsuite');name=next(iter(CASES))
    t=SafeTrace();t.checkpoint('complete')
    add_case(root,name,trace=t.serialized());add_case(root,name,trace=t.serialized())
    add_case(root,'PRIVATE-KEY-TEST',trace=t.serialized());ET.ElementTree(root).write(p)
    report=case_details(p)
    assert not report['complete'] and report['duplicate_cases']==1 and report['unknown_cases']==1
    assert len(report['missing_cases'])==3 and 'PRIVATE-KEY-TEST' not in json.dumps(report)


def test_pass_without_final_checkpoint_or_missing_trace_not_certified(tmp_path):
    p=tmp_path/'report.xml';root=ET.Element('testsuite');t=SafeTrace();t.checkpoint('seed_catalog')
    for i,name in enumerate(CASES):
        add_case(root,name,trace=t.serialized() if i else None)
    ET.ElementTree(root).write(p)
    assert not case_details(p)['complete']


def test_trace_bounds_and_nested_payload_redaction():
    t=SafeTrace()
    for _ in range(MAX_EVENTS+1):t.checkpoint('complete')
    assert t.truncated and len(t.events)==MAX_EVENTS
    assert clean_event({'event':'reply_shape','source':'secret','van_buren':{'x':'secret'},'numbered_lines':10000,'raw':'secret'})=={'event':'reply_shape','source':'unknown_source'}
    assert clean_event({'event':{'key':'secret'}}) is None


def test_actual_pytest_junit_keeps_trace_after_assertion_failure(tmp_path):
    # Real pytest fixture teardown, not hand-built XML: mirrors test_live_sdk.
    script=tmp_path/'test_probe.py'
    script.write_text('''import pytest\nimport sys\nsys.path.insert(0, %r)\nfrom diagnostics import SafeTrace, PROPERTY\n@pytest.fixture\ndef trace(record_property):\n    t=SafeTrace()\n    yield t\n    record_property(PROPERTY,t.serialized())\n@pytest.mark.parametrize('repeat',[1,2],ids=['repeat-1','repeat-2'])\ndef test_named_focus_pdf_followup_and_idempotency(trace,repeat):\n    trace.checkpoint('named_focus')\n    assert repeat == 1, 'PRIVATE-KEY-TEST'\n    trace.checkpoint('complete')\n''' % str(Path(__file__).parent))
    path=tmp_path/'real.xml'
    result=subprocess.run([sys.executable,'-m','pytest',str(script),'-q','--junitxml='+str(path)],capture_output=True,timeout=30)
    assert result.returncode==1
    report=case_details(path)
    assert [(c['status'],c['last_checkpoint'],c['trace_status']) for c in report['cases']]==[('PASS','complete','RECORDED'),('FAIL','named_focus','RECORDED')]
    assert 'PRIVATE-KEY-TEST' not in json.dumps(report)


def test_catalog_reconciliation_exports_only_fixed_reason_codes():
    t=SafeTrace()
    t.add('catalog_reconciliation', applied=False, search_batches=2,
          reasons=['no_exact_criteria','unverified_inventory','PRIVATE-KEY-TEST',{'raw':'secret'}],
          raw='PRIVATE-KEY-TEST')
    assert t.events==[{'event':'catalog_reconciliation','applied':False,'search_batches':2,
                      'reasons':['no_exact_criteria','unverified_inventory']}]
    assert 'PRIVATE-KEY-TEST' not in t.serialized()
    assert clean_event({'event':'catalog_reconciliation','applied':'secret','search_batches':10000,
        'reasons':['canonical_rendered','secret']})=={'event':'catalog_reconciliation','reasons':['canonical_rendered']}
