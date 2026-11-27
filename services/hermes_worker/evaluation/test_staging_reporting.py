"""Ensure certification never counts omitted cases or exports raw error text."""
from xml.etree import ElementTree as ET
import json
import pytest
from run_staging import summarize,expected_cases,run
from diagnostics import PROPERTY,SafeTrace


def fixture_xml(path, lane='model', *, missing=False, duplicate=False, bad=False, checkpoint='complete', unknown=False):
    root=ET.Element('testsuite')
    for index,(module,name) in enumerate(expected_cases(lane)):
        if missing and index==0:continue
        row=ET.SubElement(root,'testcase',classname=module,name=name)
        props=ET.SubElement(row,'properties');ET.SubElement(props,'property',name='staging_checkpoint',value=checkpoint)
        trace=SafeTrace();trace.add('runtime_started');ET.SubElement(props,'property',name=PROPERTY,value=trace.serialized())
        if bad and index==0:ET.SubElement(row,'failure',message='never-export-key-https://example.invalid/token').text='private'
        if duplicate and index==0:ET.SubElement(root,'testcase',classname=module,name=name)
    if unknown:ET.SubElement(root,'testcase',classname='untrusted',name='private-secret')
    ET.ElementTree(root).write(path)


def test_exact_case_report(tmp_path):
    path=tmp_path/'x.xml';fixture_xml(path);r=summarize(path,'model')
    assert r['passed']==r['expected']==r['total']==18 and not r['missing_cases']


@pytest.mark.parametrize('kind',['missing','duplicate','bad','unknown'])
def test_invalid_evidence_detected(tmp_path,kind):
    path=tmp_path/'x.xml';fixture_xml(path,**{kind:True});r=summarize(path,'model')
    assert r['missing_cases'] or r['duplicate_cases'] or r['failed'] or r['unknown_cases']
    assert 'never-export-key' not in json.dumps(r) and 'private-secret' not in json.dumps(r)


def test_no_completion_or_invalid_checkpoint(tmp_path):
    path=tmp_path/'x.xml';fixture_xml(path,checkpoint='private-secret');r=summarize(path,'model')
    assert r['incomplete']==18 and r['passed']==0 and 'private-secret' not in json.dumps(r)


def test_absent_report_not_passed(tmp_path):
    r=summarize(tmp_path/'missing.xml','model');assert r['total']==0 and len(r['missing_cases'])==18


def test_model_requires_explicit_opt_in(tmp_path,monkeypatch):
    monkeypatch.setenv('ENVIRONMENT','test');monkeypatch.setenv('DATABASE_URL','sqlite://')
    monkeypatch.delenv('HEI06_RUN_MODEL',raising=False)
    r=run('model','a'*40,tmp_path/'evidence.json');assert r['status']=='NOT_RUN'


def test_comparison_does_not_accept_swapped_counts():
    from staging_scenarios import comparison_facts
    comparison_facts('Van Buren has one bathroom, while Oakwood has two bathrooms.')
    with pytest.raises(AssertionError):comparison_facts('Van Buren has 2 bathrooms, Oakwood has 1 bathroom.')
