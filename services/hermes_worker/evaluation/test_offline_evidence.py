"""Offline diagnostics export only fixed metadata, never arbitrary traceback text."""
import json
from xml.etree import ElementTree as ET
from offline_evidence import PROPERTY, parse_failures, failure_shape


def test_known_dispatch_failure_location():
    try:
        exec(compile("raise PermissionError('Hermes delivery changed after preparation; review instead of sending.')", 'live_service.py','exec'))
    except PermissionError as exc:
        result=failure_shape(exc,'call')
    assert result['reason']=='dispatch_changed' and result['type']=='PermissionError'
    assert result['locations'][-1]=={'file':'live_service.py','line':1}


def test_offline_export_filters_arbitrary_fields():
    case=ET.Element('testcase');props=ET.SubElement(case,'properties')
    record={'phase':'call','type':'private-error','reason':'https://example.invalid/private','locations':[
        {'file':'private-secret.py','line':1},{'file':'staging_scenarios.py','line':150,'source':'secret'},
        {'file':'live_service.py','line':1000000}], 'raw':'private'}
    ET.SubElement(props,'property',name=PROPERTY,value=json.dumps(record))
    ET.SubElement(case,'failure',message='private-key').text='secret traceback'
    result=parse_failures(case)
    assert result==[{'phase':'call','type':'unknown','reason':'unknown','locations':[{'file':'staging_scenarios.py','line':150}]}]
    assert all(x not in json.dumps(result) for x in ('secret','private','https://'))


def test_malformed_offline_evidence_is_omitted():
    case=ET.Element('testcase');props=ET.SubElement(case,'properties')
    for value in ('{bad json',json.dumps({'phase':'unknown','locations':[]}),json.dumps({'phase':'call','locations':None})):
        ET.SubElement(props,'property',name=PROPERTY,value=value)
    assert parse_failures(case)==[]


def test_failure_hook_writes_sanitized_junit_property(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    source=tmp_path/'test_staging_harness.py'
    source.write_text("def test_failure():\n    assert False, 'private-secret https://example.invalid/private'\n")
    xml=tmp_path/'results.xml'
    env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
    env['PYTHONPATH']=str(Path(__file__).resolve().parent)+os.pathsep+env.get('PYTHONPATH','')
    proc=subprocess.run([sys.executable,'-m','pytest','-q','-p','offline_evidence','--tb=no',
        '--show-capture=no','--junitxml='+str(xml),str(source)],env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    assert proc.returncode==1 and xml.is_file()
    case=next(ET.parse(xml).iter('testcase'))
    records=parse_failures(case)
    assert records and records[0]['type']=='AssertionError'
    assert records[0]['locations'][-1]=={'file':'test_staging_harness.py','line':2}
    assert all(x not in json.dumps(records) for x in ('private-secret','https://'))
