"""Closed-gate smoke from a separate container on an internal Docker network.
No readiness override, no database, no model or provider calls.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path
import httpx


def probe(commit, output):
    if not re.fullmatch(r'[a-f0-9]{40}',commit):raise ValueError('Full candidate SHA required')
    report={'schema':'hei06-private-network/1','candidate_commit':commit,'status':'FAIL',
        'production_readiness':'CLOSED','checks':{},'model_calls':0,'provider_calls':0}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        assert os.environ.get('ENVIRONMENT')=='test' and os.environ.get('DATABASE_URL')=='sqlite://'
        token=os.environ['HERMES_INTERNAL_TOKEN'];assert len(token)>=32
        with httpx.Client(base_url='http://bp-hermes:8080',trust_env=False,follow_redirects=False,timeout=3) as client:
            body={'job_id':'not-a-real-job','run_id':'not-a-real-run'}
            for attempt in range(40):
                try:
                    unauthorized=client.post('/internal/prepare',json=body);break
                except (httpx.ConnectError,httpx.ConnectTimeout):time.sleep(.5)
            else:raise RuntimeError('Private service did not start')
            report['checks']['missing_token_401']=unauthorized.status_code==401
            report['checks']['wrong_token_401']=client.post('/internal/prepare',json=body,headers={'Authorization':'Bearer invalid'}).status_code==401
            good={'Authorization':'Bearer '+token}
            report['checks']['closed_gate_503']=client.post('/internal/prepare',json=body,headers=good).status_code==503
            report['checks']['extra_prompt_422']=client.post('/internal/prepare',json={**body,'prompt':'must not be accepted'},headers=good).status_code==422
            report['checks']['no_public_schema_404']=client.get('/openapi.json').status_code==404
        report['status']='PASS' if len(report['checks'])==5 and all(report['checks'].values()) else 'FAIL'
    except Exception as exc:report['reason']=type(exc).__name__
    finally:output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True));return 0 if report['status']=='PASS' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raise SystemExit(probe(a.commit,a.output))
