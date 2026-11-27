"""Execute isolated staging acceptance; publish allowlisted case/checkpoint evidence.

The report is NOT a readiness token. The original HEI-06 four-case lane is
unchanged. No raw pytest, JUnit, prompts, responses, URLs or secrets exported.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET
from run_lane import sdk_revision
from diagnostics import parse_trace
from lifecycle_evidence import parse_lifecycle
from offline_evidence import parse_failures
from staging_scenarios import CASE_IDS, CHECKPOINTS

TRANSPORT = ('test_closed_gate_and_auth','test_unknown_job_and_invalid_run',
             'test_socket_worker_receipt_and_replay','test_socket_queued_receipt_no_duplicate')
LANES = {
    'offline': ('test_staging_transport.py','test_staging_harness.py'),
    'model': ('test_staging_conversations.py',),
    'imperfect': ('test_turn_lifecycle_harness.py',),
}


def expected_cases(lane):
    if lane=='model':return {('test_staging_conversations',f'test_staging_scenario[{i}]'):i for i in CASE_IDS}
    if lane=='imperfect':
        return {('test_turn_lifecycle_harness',f'test_lifecycle_imperfect_sdk[{family}-{i}]'):f'{family}-{i}'
                for family in ('temporary','no-match','visit') for i in (1,2,3)}
    return {**{('test_staging_transport',n):n for n in TRANSPORT},
            **{('test_staging_harness',f'test_staging_harness[{i}]'):i for i in CASE_IDS}}


def summarize(path, lane):
    expected=expected_cases(lane); found={}; duplicate=0; unknown=0
    cases=list(ET.parse(path).iter('testcase')) if path.is_file() else []
    for case in cases:
        key=((case.get('classname') or '').rsplit('.',1)[-1],case.get('name'))
        if key not in expected:unknown+=1;continue
        identity=expected[key]
        if identity in found:duplicate+=1;continue
        status=('FAIL' if case.find('failure') is not None or case.find('error') is not None else
                'SKIP' if case.find('skipped') is not None else 'PASS')
        codes=[prop.get('value') for prop in case.findall('properties/property') if prop.get('name')=='staging_checkpoint']
        safe=all(x in CHECKPOINTS for x in codes) and len(codes)<=20
        complete=(bool(codes) and codes[-1]=='complete') if safe else False
        events, trace_status = parse_trace(case) if lane=='model' else ([], 'NOT_REQUIRED')
        if lane=='model' and status=='PASS' and (not complete or trace_status!='RECORDED'):status='INCOMPLETE'
        found[identity]={'case':identity,'status':status,'last_checkpoint':codes[-1] if safe and codes else None,
                         'trace_status':trace_status,'events':events}
        if lane=='model':found[identity]['lifecycle']=parse_lifecycle(case)
        elif status=='FAIL':found[identity]['offline_failures']=parse_failures(case)
    missing=sorted(set(expected.values())-set(found))
    result={'expected':len(expected),'total':len(cases),'passed':sum(x['status']=='PASS' for x in found.values()),
            'failed':sum(x['status']=='FAIL' for x in found.values()),'skipped':sum(x['status']=='SKIP' for x in found.values()),
            'incomplete':sum(x['status']=='INCOMPLETE' for x in found.values()),'unknown_cases':unknown,
            'duplicate_cases':duplicate,'missing_cases':missing,'cases':[found[x] for x in sorted(found)]}
    return result


def run(lane,commit,output):
    if not re.fullmatch(r'[a-f0-9]{40}',commit):raise ValueError('Full candidate SHA required')
    report={'schema':'hei06-controlled-staging/1','candidate_commit':commit,'lane':lane,
        'status':'NOT_RUN','sdk_revision':None,'model':'openai/gpt-4o-mini' if lane=='model' else None,
        'inference':'real_sdk_openrouter' if lane=='model' else 'simulated','http_transport':'loopback_tcp',
        'database':'isolated_sqlite','real_message_provider_calls':0,'real_calendar_calls':0,
        'production_readiness':'CLOSED','published_production_policy_tested':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        if os.environ.get('ENVIRONMENT')!='test' or os.environ.get('DATABASE_URL')!='sqlite://':
            report['reason']='ISOLATED_ENVIRONMENT_REQUIRED';return report
        if lane=='model' and (os.environ.get('HEI06_RUN_MODEL')!='1' or os.environ.get('OPENROUTER_API_KEY') in (None,'','test-only')):
            report['reason']='EXPLICIT_MODEL_OPT_IN_AND_KEY_REQUIRED';return report
        if lane!='model' and os.environ.get('OPENROUTER_API_KEY')!='test-only':
            report['reason']='OFFLINE_TEST_KEY_REQUIRED';return report
        report['sdk_revision']=sdk_revision()
        with tempfile.TemporaryDirectory(prefix='hei06-controlled-') as tmp:
            junit=Path(tmp)/'results.xml'
            args=[sys.executable,'-m','pytest','-q',*[str(Path(__file__).with_name(x)) for x in LANES[lane]],
                '--disable-warnings','--show-capture=no','--tb=no','--junitxml='+str(junit)]
            env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
            if lane!='model':
                args[3:3]=['-p','offline_evidence']
                env['PYTHONPATH']=str(Path(__file__).resolve().parent)+os.pathsep+env.get('PYTHONPATH','')
            with (Path(tmp)/'pytest.log').open('w') as stream:
                completed=subprocess.run(args,env=env,
                    stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
            report.update(summarize(junit,lane),exit_code=completed.returncode)
            ok=(completed.returncode==0 and report['passed']==report['expected']==report['total'] and
                not any(report[k] for k in ('failed','skipped','incomplete','unknown_cases','duplicate_cases','missing_cases')))
            report['status']='PASS' if ok else 'FAIL'
            if not ok:report['reason']='TESTS_FAILED_OR_INCOMPLETE'
    except (Exception,KeyboardInterrupt) as exc:
        report['status']='FAIL';report['reason']=type(exc).__name__
    finally:
        output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lane',choices=LANES,required=True)
    p.add_argument('--commit',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=run(a.lane,a.commit,a.output)
    print(json.dumps(result,sort_keys=True));return 0 if result['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
