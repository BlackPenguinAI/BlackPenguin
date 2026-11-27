"""Manual HEI-06B.1 provisioning on a dedicated non-production Docker host."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from manage import BASE, ROOT, clean_env, command, head, init, read_state

BASELINE='893ecc290fc4e51ee54d818af23f0728a28011b7'
PROVIDER=BASE/'provider_isolation'
MODEL_KEY='HEI06A2_CONTINUOUS_OPENROUTER_API_KEY'


def require(condition, reason):
    if not condition: raise ValueError(reason)


def verify_checkout(sha):
    require(head()==sha and not command(['git','status','--porcelain','--untracked-files=all'],capture=True).strip(),'candidate_not_clean')
    command(['git','merge-base','--is-ancestor',BASELINE,sha])
    paths=command(['git','diff','--name-only','-z',BASELINE,sha],capture=True).split('\0')
    prefix='services/hermes_worker/persistent_staging/'
    allowed={'.github/workflows/hermes-hei06a2-persistent-staging.yml'} | {prefix+x for x in ('permanent.py','permanent.model.compose.yml','test_provider_isolation.py','HEI_06B1_PERMANENT_STAGING_PROVIDER_ISOLATION.md')}
    require(all(not p or p in allowed or p.startswith(prefix+'provider_isolation/') for p in paths),'certified_baseline_changed')
    # Do not use a production checkout or build context containing dotenv secrets.
    for parent in (ROOT,ROOT/'backend',ROOT/'frontend',BASE):
        require(not any(p.is_file() and p.name not in {'.env.example','.env.sample','.env.template'} for p in parent.glob('.env*')),'dotenv_present')


def private_file(path):
    require(path.is_file() and not path.is_symlink() and stat.S_IMODE(path.stat().st_mode)==0o600 and path.stat().st_uid==os.getuid(),'private_file_required')
    return path.read_text().strip()


def state_directory(path):
    require(path.is_absolute() and not path.is_symlink(),'absolute_state_required')
    path=path.resolve()
    require(path!=ROOT and ROOT not in path.parents and not any(x in str(path) for x in ':\n\r$'),'state_outside_checkout_required')
    return path


def write_once(path, value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(value+'\n')


def provider_files(directory):
    require(directory.is_dir() and not directory.is_symlink(),'provider_directory_required')
    for name in ('policy.json','privkey.pem','fullchain.pem'):
        p=directory/name
        require(p.is_file() and not p.is_symlink(),'provider_file_missing')
        require(p.stat().st_uid==10001 and p.stat().st_gid==10001 and stat.S_IMODE(p.stat().st_mode)==0o400,'provider_file_permissions')
    j=directory/'journal'
    require(j.is_dir() and not j.is_symlink() and j.stat().st_uid==10001 and j.stat().st_gid==10001 and stat.S_IMODE(j.stat().st_mode)==0o700,'journal_permissions')


def topology(obj, project, service, nets, ports, user=None):
    labels=obj['Config'].get('Labels') or {}
    require(labels.get('com.docker.compose.project')==project and labels.get('com.docker.compose.service')==service,'container_scope')
    require(obj['State']['Running'] and set(obj['NetworkSettings']['Networks'])==nets,'network_scope')
    actual={(name,item['HostIp'],item['HostPort']) for name,items in (obj['NetworkSettings']['Ports'] or {}).items() for item in (items or [])}
    require(actual==ports,'port_scope')
    if user: require(obj['Config']['User']==user,'container_identity')


def operate(args):
    directory=state_directory(args.state)
    if args.action=='init':
        require(args.confirm_dedicated_host,'dedicated_host_confirmation_required')
        verify_checkout(head());init(directory);return
    values=read_state(directory);sha=values['STAGE_COMMIT'];env=clean_env()
    project='bp-hei06a2-'+values['STAGE_INSTANCE'][:16]; ingress=project+'-quarantine'
    def docker(*cmd,capture=False,extra=None):
        return command(['docker',*cmd],capture=capture,env=env if extra is None else {**env,**extra})
    def inspect(cid):return json.loads(docker('inspect',cid,capture=True))[0]
    # Dedicated host: fail if any unrelated container exists (including stopped).
    # Stop commands remain available for the known project even if another service appears.
    if args.action in ('up','webhook-up','verify'):
        require(args.confirm_dedicated_host,'dedicated_host_confirmation_required');verify_checkout(sha)
        for cid in docker('ps','-aq',capture=True).split():
            require((inspect(cid)['Config'].get('Labels') or {}).get('com.docker.compose.project') in {project,ingress},'unrelated_container_on_host')
    core=['compose','--project-name',project,'--project-directory',str(BASE),'--env-file',str(directory/'staging.env'),'-f',str(BASE/'compose.yml')]
    active=core+['-f',str(BASE/'continuous.compose.yml')]
    mode_path=directory/'runtime.mode';model=False;key=''
    if args.action=='up':
        model=args.model
        if mode_path.exists():require(private_file(mode_path)==('model' if model else 'offline'),'runtime_mode_change_requires_review')
        if model:
            key=private_file(directory/'openrouter.key')
            require(16<=len(key)<=512 and key!='test-only' and not any(c.isspace() for c in key),'model_key_invalid')
        if not mode_path.exists():write_once(mode_path,'model' if model else 'offline')
    elif mode_path.exists():
        mode=private_file(mode_path);require(mode in {'model','offline'},'runtime_mode_invalid');model=mode=='model'
    if model:active+=['-f',str(BASE/'permanent.model.compose.yml')]
    def core_run(*cmd,derived=False,capture=False):return docker(*(active if derived else core),*cmd,capture=capture,extra={MODEL_KEY:key} if derived else None)
    provider=directory/'provider'; bind='0.0.0.0' if args.public else '127.0.0.1';port='443' if args.public else '18443'
    p_env={'STAGE_COMMIT':sha,'HEI06B_CONFIG':str(provider),'HEI06B_BIND':bind,'HEI06B_PORT':port}
    p_cmd=['compose','--project-name',ingress,'--project-directory',str(PROVIDER),'--env-file',str(directory/'staging.env'),'-f',str(PROVIDER/'compose.yml')]
    def receiver(*cmd,capture=False):return docker(*p_cmd,*cmd,capture=capture,extra=p_env)
    def info(run,service):
        cid=run('ps','-q',service,capture=True).strip();require(bool(re.fullmatch(r'[0-9a-f]{12,64}',cid)),'service_not_running');return inspect(cid)
    def verify_core():
        for name in ('api','bp-hermes','staging-postgres','frontend'):
            obj=info(core_run,name);nets={project+'_private'};ports=set();user=None
            if name=='frontend':nets.add(project+'_ingress');ports={('8080/tcp','127.0.0.1','18082')}
            if name=='bp-hermes' and model:nets.add(project+'_model_egress')
            if name in ('api','bp-hermes'):
                user='10001:10001';expected='bp-hei06a2-continuous-'+('api' if name=='api' else 'sdk')+':'+sha
                require(obj['Config']['Image']==expected,'derived_image_required')
                names={v.split('=',1)[0]:v.split('=',1)[1] for v in obj['Config']['Env'] if '=' in v}
                require(not names.get('TELNYX_API_KEY') and not names.get('TWILIO_AUTH_TOKEN') and not names.get('GOOGLE_APPLICATION_CREDENTIALS'),'external_provider_key')
                require(bool(names.get(MODEL_KEY))==(name=='bp-hermes' and model),'model_key_scope')
            topology(obj,project,name,nets,ports,user)
        require(docker('network','inspect',project+'_private','--format','{{.Internal}}',capture=True).strip()=='true','private_network_required')
    def verify_receiver():
        obj=info(receiver,'receiver');topology(obj,ingress,'receiver',{ingress+'_quarantine'},{('8443/tcp',bind,port)},'10001:10001')
        require(obj['HostConfig']['ReadonlyRootfs'] and set(obj['HostConfig']['CapDrop'])=={'ALL'},'receiver_hardening_missing')
        require(not any(v.startswith(('TELNYX_API_KEY=','DATABASE_URL=','HERMES_INTERNAL_TOKEN=',MODEL_KEY+'=')) for v in obj['Config']['Env']),'receiver_has_private_credentials')
    if args.action=='up':
        marker=directory/'foundation.ready'
        if not marker.exists():
            # Reuse the certified bootstrap and administrative publication before
            # any continuous worker can claim a job. Never rerun on a live stack.
            command([sys.executable,str(BASE/'manage.py'),'up',str(directory)],env=env)
            command([sys.executable,str(BASE/'manage.py'),'probe',str(directory)],env=env)
            write_once(marker,sha)
        else:require(private_file(marker)==sha,'foundation_marker_mismatch')
        # Keep the already-certified source transformations in the derived images.
        core_run('build')
        for service,root in [('api','/app'),('sdk','/opt/blackpenguin')]:
            docker('build','--build-arg','BASE_IMAGE=bp-hei06a2-'+service+':'+sha,'--build-arg','APP_ROOT='+root,'-t','bp-hei06a2-continuous-'+service+':'+sha,'-f',str(BASE/'continuous.Dockerfile'),str(BASE))
        core_run('stop','frontend','api','bp-hermes')
        core_run('up','-d','--wait','staging-postgres')
        core_run('run','--rm','--no-deps','api','bootstrap')
        core_run('up','-d','--wait','--no-build','--no-deps','--force-recreate','api','bp-hermes','frontend',derived=True)
        verify_core();print('HEI06B1_CORE_READY: fixture-only; external sends disabled.')
    elif args.action=='webhook-up':
        verify_core();provider_files(provider)
        receiver('build');receiver('up','-d','--wait','--no-build');verify_receiver()
        print('HEI06B1_RECEIVER_STARTED: verify TLS from outside before configuring the profile.')
    elif args.action=='verify':
        verify_core();verify_receiver();print('HEI06B1_TOPOLOGY_PASS: TLS/provider delivery not certified by topology.')
    elif args.action=='status':
        core_run('ps');receiver('ps')
    elif args.action=='stats':receiver('exec','-T','receiver','python','/srv/receiver.py','stats')
    elif args.action=='webhook-stop':receiver('stop','receiver')
    elif args.action=='stop':
        # Emergency stop: both isolated projects, retain all databases and evidence.
        try:receiver('stop','receiver')
        finally:core_run('stop','frontend','api','bp-hermes')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['init','up','webhook-up','verify','status','stats','webhook-stop','stop']);p.add_argument('state',type=Path);p.add_argument('--confirm-dedicated-host',action='store_true');p.add_argument('--model',action='store_true');p.add_argument('--public',action='store_true');args=p.parse_args()
    try:operate(args)
    except Exception as exc:
        # Never emit command output/args, configuration, secrets or raw HTTP data.
        print('HEI06B1 command failed: '+type(exc).__name__,file=sys.stderr);raise SystemExit(2) from None

if __name__=='__main__':main()
