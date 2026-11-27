"""Hosted-CI-only HTTPS and Docker isolation acceptance. No provider calls."""
import argparse
import http.client
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time
import traceback
import re

from provider_isolation import fixture, receiver
from manage import BASE, clean_env, read_state, head
from permanent import topology, require


def evaluate(state, report):
    temp=Path(os.environ['RUNNER_TEMP']).resolve()
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted' and temp in state.resolve().parents,'hosted_ci_only')
    values=read_state(state);sha=values['STAGE_COMMIT'];require(head()==sha,'candidate_mismatch')
    project='bp-hei06a2-'+values['STAGE_INSTANCE'][:16];name=project+'-quarantine'
    base=state/'provider-ci';base.mkdir(mode=0o700);sign=base/'signing';cfg=fixture.setup(sign);fixture.certificate(sign)
    config=base/'config';config.mkdir(mode=0o700);(config/'journal').mkdir(mode=0o700)
    for f in ('policy.json','privkey.pem','fullchain.pem'):
        shutil.copyfile(sign/f,config/f);(config/f).chmod(0o400)
    # This affects only disposable synthetic files within RUNNER_TEMP.
    subprocess.run(['sudo','chown','10001:10001',*[str(config/f) for f in ('policy.json','privkey.pem','fullchain.pem','journal')]],check=True)
    env={**clean_env(),'STAGE_COMMIT':sha,'HEI06B_CONFIG':str(config),'HEI06B_BIND':'127.0.0.1','HEI06B_PORT':'18443'}
    compose=['docker','compose','--project-name',name,'--project-directory',str(BASE/'provider_isolation'),'--env-file',str(state/'staging.env'),'-f',str(BASE/'provider_isolation/compose.yml')]
    def call(args):return subprocess.run(args,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout
    def run(*args):return call(compose+list(args))
    def inspect():
        cid=run('ps','-q','receiver').strip();obj=json.loads(call(['docker','inspect',cid]))[0]
        topology(obj,name,'receiver',{name+'_quarantine'},{('8443/tcp','127.0.0.1','18443')},'10001:10001')
        require(obj['HostConfig']['ReadonlyRootfs'] and set(obj['HostConfig']['CapDrop'])=={'ALL'},'receiver_hardening_missing')
        require(not any(v.startswith(('TELNYX_API_KEY=','DATABASE_URL=','HERMES_INTERNAL_TOKEN=','HEI06A2_CONTINUOUS_OPENROUTER_API_KEY=')) for v in obj['Config']['Env']),'private_credentials_exposed')
        info=json.loads(call(['docker','network','inspect',name+'_quarantine']))[0]
        require(set(info['Containers'])=={obj['Id']},'unexpected_quarantine_peer')
        # Verify all currently running BP core containers are on disjoint networks.
        for other in call(['docker','ps','-q','--filter','label=com.docker.compose.project='+project]).split():
            o=json.loads(call(['docker','inspect',other]))[0]
            require(name+'_quarantine' not in o['NetworkSettings']['Networks'],'quarantine_joined_core')
    ctx=ssl.create_default_context(cafile=str(sign/'fullchain.pem'))
    def request(method,path,raw=None,headers=None):
        client=http.client.HTTPSConnection('127.0.0.1',18443,context=ctx,timeout=5)
        try:
            client.request(method,path,body=raw,headers=headers or {});resp=client.getresponse();return resp.status,json.loads(resp.read())
        finally:client.close()
    def ready():
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                if request('GET','/')[0]==404:return
            except (OSError,http.client.HTTPException):time.sleep(.5)
        raise RuntimeError('quarantine_tls_not_ready')
    def signed(value, stamp=None):
        raw,sig,ts=fixture.sign(sign,value,stamp)
        return raw,{'Content-Type':'application/json','telnyx-signature-ed25519':sig,'telnyx-timestamp':ts}
    try:
        report['checkpoint']='build_and_start';run('build');run('up','-d','--no-build');ready();inspect();report['checks']['separate_network_and_no_keys']=True
        report['checkpoint']='https_denials';data=fixture.event(cfg);raw,headers=signed(data)
        require(request('GET','/api/v1/auth/login')[0]==404,'admin_route_exposed')
        require(request('POST',receiver.PATH,raw,{'Content-Type':'application/json'})[0]==401,'missing_signature_accepted')
        require(request('POST',receiver.PATH,raw+b' ',headers)[0]==401,'tamper_accepted')
        old,old_headers=signed(data,int(time.time())-301);require(request('POST',receiver.PATH,old,old_headers)[0]==401,'stale_signature_accepted')
        foreign=fixture.event(cfg);foreign['data']['payload']['from']['phone_number']='+12025550199'
        invalid,invalid_headers=signed(foreign);require(request('POST',receiver.PATH,invalid,invalid_headers)[0]==403,'foreign_sender_accepted')
        report['checks']['signed_https_negative_cases']=True
        report['checkpoint']='durable_quarantine';require(request('POST',receiver.PATH,raw,headers)==(200,{'status':'quarantined'}),'event_not_quarantined')
        data['meta']['attempt']=2;again,again_headers=signed(data);require(request('POST',receiver.PATH,again,again_headers)==(200,{'status':'duplicate'}),'retry_not_idempotent')
        run('up','-d','--no-build','--force-recreate');ready();inspect()
        again,again_headers=signed(data);require(request('POST',receiver.PATH,again,again_headers)==(200,{'status':'duplicate'}),'recreation_lost_evidence')
        data['data']['payload']['text']='tampered identity';changed,ch=signed(data);require(request('POST',receiver.PATH,changed,ch)[0]==409,'identity_conflict_accepted')
        count=json.loads(run('exec','-T','receiver','python','/srv/receiver.py','stats'))
        require(count=={'quarantined_unique_events':1,'commercial_ingress':'DISABLED','real_outbound':'DISABLED','production_readiness':'CLOSED'},'unexpected_journal_count')
        report['checks']['durable_idempotent_quarantine']=True;report['quarantined_unique_events']=1
        report['checkpoint']='stop_receiver';run('stop','receiver')
        require(not run('ps','-q','--status','running','receiver').strip(),'receiver_not_stopped');report['checks']['kill_switch_stops_receiver']=True
    finally:
        # Capture only known safe receiver startup events before removing it.
        if sys.exc_info()[0] is not None:
            try:
                logs=run('logs','--no-color','--no-log-prefix','--tail','100','receiver')
                report['receiver_events']=[line for line in logs.splitlines() if re.fullmatch(r'HEI06B1_(?:QUARANTINE_READY|STARTUP_FAILURE [A-Za-z][A-Za-z0-9_]{0,79})',line)]
            except Exception as exc:
                report['diagnostics_error']=type(exc).__name__
        try:
            run('down','--remove-orphans')
            for args in (['ps','-aq'],['network','ls','-q']):
                require(not call(['docker',*args,'--filter','label=com.docker.compose.project='+name]).strip(),'quarantine_resources_remain')
        except Exception as exc:
            report['cleanup_error']=type(exc).__name__
            raise
    report['checks']['cleanup']=True;report.update(status='PASS',checkpoint='complete')


def main():
    p=argparse.ArgumentParser();p.add_argument('state',type=Path);a=p.parse_args()
    report={'schema':'hei06b1-provider-isolation/1','status':'FAIL','checkpoint':'start','checks':{},'permanent_server_deployment':'NOT_RUN','actual_telnyx_delivery':'NOT_RUN','commercial_ingress':'DISABLED','real_outbound':'DISABLED','production_readiness':'CLOSED'}
    try:report['candidate_commit']=read_state(a.state)['STAGE_COMMIT'];evaluate(a.state,report)
    except Exception as exc:
        report['exception_type']=type(exc).__name__
        report['locations']=[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)][-8:]
        if isinstance(exc,subprocess.CalledProcessError):report['subprocess_exit_code']=exc.returncode
    print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)

if __name__=='__main__':main()
