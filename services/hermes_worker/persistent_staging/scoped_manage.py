"""Local Docker operator entrypoint. No browser or provider ingress is installed."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from manage import BASE, ROOT, clean_env, read_state, head, command
from scoped_policy import KEY, check_input, require, ScopedDenied


def topology(values, env, compose, project):
    cid=command(compose+['ps','-q','bp-hermes'],capture=True,env=env).strip()
    require(bool(cid) and '\n' not in cid,'sdk_container_missing')
    obj=json.loads(command(['docker','inspect',cid],capture=True,env=env))[0]
    cfg=obj['Config']; labels=cfg['Labels']; ns=obj['NetworkSettings']
    require(labels.get('com.docker.compose.project')==project and labels.get('com.docker.compose.service')=='bp-hermes','wrong_container')
    require(cfg['Image']=='bp-hei06a2-sdk:'+values['STAGE_COMMIT'] and cfg['User']=='10001:10001' and obj['State']['Running'],'wrong_sdk_image_or_user')
    require(set(ns['Networks'])=={project+'_private'} and not any((ns.get('Ports') or {}).values()),'unexpected_sdk_network')
    require(command(['docker','network','inspect',project+'_private','--format','{{.Internal}}'],capture=True,env=env).strip()=='true','not_private_network')
    return cid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['init','grant','enqueue','process','revoke','status'])
    p.add_argument('state_dir',type=Path)
    p.add_argument('--event-id')
    p.add_argument('--message-file',type=Path)
    p.add_argument('--model',action='store_true',help='Explicitly allow SDK-only temporary Internet egress for one process')
    a=p.parse_args()
    require(a.state_dir.is_absolute() and not a.state_dir.is_symlink(),'invalid_state_directory')
    d=a.state_dir.resolve(); require(d!=ROOT and ROOT not in d.parents,'state_must_be_outside_git')
    v=read_state(d); require(head()==v['STAGE_COMMIT'],'candidate_changed')
    require(not command(['git','status','--porcelain'],capture=True).strip(),'candidate_not_clean')
    require(not a.model or a.action=='process','model_only_for_process')
    require((a.action=='enqueue')==bool(a.message_file),'message_file_only_for_enqueue')
    require((a.action in {'enqueue','process'})==bool(a.event_id),'event_id_required_only_for_turn')
    payload=None
    if a.message_file:
        with a.message_file.open('rb') as f: payload=f.read(4001)
        require(len(payload)<=4000,'message_too_long');check_input(a.event_id,payload.decode('utf-8'))
    env=clean_env();project='bp-hei06a2-'+v['STAGE_INSTANCE'][:16]
    compose=['docker','compose','--project-name',project,'--project-directory',str(BASE),'--env-file',str(d/'staging.env'),'-f',str(BASE/'compose.yml')]
    cid=topology(v,env,compose,project)
    args=compose+['exec','-T']
    network=project+'_scoped_egress';created=False;connected=False
    try:
        if a.model:
            key=os.environ.get(KEY,''); require(bool(key) and key!='test-only','model_key_missing')
            # Do not pass the key as an argv value or persist it in Compose.
            env[KEY]=key;args+=['-e',KEY]
            command(['docker','network','create','--label','com.docker.compose.project='+project,network],capture=True,env=env)
            created=True
            command(['docker','network','connect',network,cid],capture=True,env=env);connected=True
        args+=['bp-hermes','python','/opt/stage/scoped_runtime.py',a.action]
        if a.event_id:args+=['--event-id',a.event_id]
        # Output from scoped_runtime is sanitized. No raw Docker stderr/SDK output.
        result=subprocess.run(args,cwd=ROOT,env=env,input=payload if payload is not None else b'',stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        lines=result.stdout.decode('utf-8',errors='replace').splitlines()
        require(bool(lines),'missing_runtime_report')
        report=json.loads(lines[-1]); require(report.get('schema')=='hei06a2b-scoped-simulation/1','invalid_runtime_report')
        print(json.dumps(report,sort_keys=True))
        return result.returncode or (0 if report.get('status')=='PASS' else 1)
    finally:
        if created:
            # Even if connect failed, attempt to remove only this named network.
            if connected:
                command(['docker','network','disconnect',network,cid],capture=True,env=env)
            command(['docker','network','rm',network],capture=True,env=env)
            topology(v,env,compose,project)

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        report={'schema':'hei06a2b-scoped-simulation/1','status':'FAIL','exception_type':type(exc).__name__,'production_readiness':'CLOSED'}
        if isinstance(exc,ScopedDenied):report['reason']=str(exc)
        print(json.dumps(report,sort_keys=True))
        raise SystemExit(2)
