"""Run one certification lane and export counts and allowlisted scenario diagnostics, never raw SDK output.

Explicit failure if skipped/missing tests, mismatched revision or missing SDK.
The resulting report is evidence of this test lane, NOT an activation token.
"""
from __future__ import annotations
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET
from diagnostics import case_details
from offline_evidence import parse_failures

PINNED_SDK = 'b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb'
LANES = {
    'offline_harness': (('test_harness_offline.py', 'test_focus_grounding.py'), 33),
    'postgres_worker': ('test_candidate_postgres.py', 14),
    'openrouter_sdk': ('test_live_sdk.py', 4),
}


def sdk_revision():
    distribution = metadata.distribution('hermes-agent')
    origin = json.loads(distribution.read_text('direct_url.json') or '{}')
    revision = (origin.get('vcs_info') or {}).get('commit_id')
    if origin.get('url', '').rstrip('/') not in {'https://github.com/NousResearch/hermes-agent.git', 'https://github.com/NousResearch/hermes-agent'} or revision != PINNED_SDK:
        raise ValueError('SDK installation is not from the pinned revision')
    return revision


def counts(path):
    if not path.exists():
        return {'total':0,'passed':0,'failed':0,'skipped':0,'duplicate_cases':0}
    cases = list(ET.parse(path).iter('testcase'))
    skipped = sum(x.find('skipped') is not None for x in cases)
    failed = sum(x.find('failure') is not None or x.find('error') is not None for x in cases)
    identities = {(x.get('classname'), x.get('name')) for x in cases}
    return {'total':len(cases),'passed':len(cases)-failed-skipped,'failed':failed,'skipped':skipped,
            'duplicate_cases':len(cases)-len(identities)}


def run(lane, commit, output):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Candidate full Git SHA required')
    if os.environ.get('ENVIRONMENT') != 'test' or os.environ.get('DATABASE_URL') != 'sqlite://':
        raise ValueError('Only the isolated test runtime is supported')
    file, expected = LANES[lane]
    report = {'schema':'hei06-lane/1','candidate_commit':commit,'lane':lane,'status':'NOT_RUN',
              'expected':expected,'production_database_used':False,'real_message_provider_calls':0,
              'real_calendar_calls':0,'inference':'real_sdk_openrouter' if lane == 'openrouter_sdk' else 'simulated',
              'sdk_revision':None,'model':'openai/gpt-4o-mini' if lane == 'openrouter_sdk' else None}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        report['sdk_revision'] = sdk_revision()
        if lane == 'openrouter_sdk' and (os.environ.get('HEI06_RUN_MODEL') != '1' or not os.environ.get('OPENROUTER_API_KEY') or os.environ.get('OPENROUTER_API_KEY') == 'test-only'):
            report['reason'] = 'MODEL_OPT_IN_OR_DEDICATED_KEY_MISSING'
            return report
        if lane == 'postgres_worker' and not os.environ.get('HEI06_POSTGRES_URL'):
            report['reason'] = 'ISOLATED_POSTGRES_URL_MISSING'
            return report
        files = (file,) if isinstance(file, str) else file
        with tempfile.TemporaryDirectory(prefix='hei06-') as tmp:
            junit=Path(tmp)/'results.xml'
            env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
            args=[sys.executable,'-m','pytest','-q',*[str(Path(__file__).with_name(name)) for name in files],
                  '--disable-warnings','--show-capture=no','--tb=no','--junitxml='+str(junit)]
            if lane != 'openrouter_sdk':
                args[3:3] = ['-p', 'offline_evidence']
                env['PYTHONPATH'] = str(Path(__file__).resolve().parent) + os.pathsep + env.get('PYTHONPATH','')
            # No pytest/stdout or raw JUnit artifacts from the model lane. A
            # traceback or SDK diagnostic could include a URL or provider key.
            # Offline logs are also suppressed for consistent reporting.
            with (Path(tmp)/'pytest.log').open('w') as stream:
                result=subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=900)
            report.update(counts(junit),exit_code=result.returncode)
            if lane == 'openrouter_sdk':
                report['diagnostics'] = case_details(junit)
            elif junit.is_file():
                # Export only allowlisted locations and enum values, not test IDs or exception text.
                report['offline_failures'] = [item for case in ET.parse(junit).iter('testcase')
                    if case.find('failure') is not None or case.find('error') is not None
                    for item in [{'failures':parse_failures(case)}]]
            ok=(result.returncode==0 and report['total']==expected and report['passed']==expected
                and report['failed']==report['skipped']==report['duplicate_cases']==0)
            if lane == 'openrouter_sdk':
                ok = ok and report['diagnostics']['complete']
            report['status']='PASS' if ok else 'FAIL'
            if not ok:report['reason']='TESTS_FAILED_OR_INCOMPLETE'
    except (Exception, KeyboardInterrupt) as exc:
        report['status']='FAIL'
        # Never serialize arbitrary exception text from dependencies/providers.
        report['reason']=type(exc).__name__
    finally:
        output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lane',choices=LANES,required=True)
    p.add_argument('--commit',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=run(args.lane,args.commit,args.output)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':
    raise SystemExit(main())
