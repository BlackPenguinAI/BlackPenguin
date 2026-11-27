"""Operator CLI for the closed persistent staging stack. No production deployment.
Secrets are generated locally and never sourced as shell commands.
"""
import argparse
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
KEYS=('STAGE_INSTANCE','STAGE_JWT','STAGE_TOKEN','STAGE_DB_PASSWORD','STAGE_ADMIN_PASSWORD')


def command(args, *, capture=False, env=None):
    return subprocess.run(args,cwd=ROOT,env=env,check=True,text=True,stdout=subprocess.PIPE if capture else None).stdout


def read_state(directory):
    file=directory/'staging.env'
    if directory.is_symlink() or file.is_symlink() or not file.is_file(): raise ValueError('Missing private state file')
    if stat.S_IMODE(directory.stat().st_mode)!=0o700 or stat.S_IMODE(file.stat().st_mode)!=0o600:
        raise ValueError('State directory/file must be mode 700/600')
    values={}
    for line in file.read_text().splitlines():
        key,sep,value=line.partition('=')
        if not sep or key in values: raise ValueError('Invalid state file')
        values[key]=value
    if set(values)!=set(KEYS)|{'STAGE_COMMIT'} or any(not re.fullmatch(r'[0-9a-f]{64}',values[k]) for k in KEYS) or len(set(values[k] for k in KEYS))!=len(KEYS) or not re.fullmatch(r'[0-9a-f]{40}',values['STAGE_COMMIT']):
        raise ValueError('Invalid state values')
    return values


def head(): return command(['git','rev-parse','HEAD'],capture=True).strip()


def init(directory):
    directory.mkdir(mode=0o700,parents=False,exist_ok=False)
    values={k:secrets.token_hex(32) for k in KEYS}; values['STAGE_COMMIT']=head()
    fd=os.open(directory/'staging.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(''.join(f'{k}={v}\n' for k,v in values.items()))
    print('Initialized private staging state; keep staging.env outside Git.')


def clean_env():
    # No COMPOSE_* variables, provider keys, or inherited staging values.
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise ValueError('Remote Docker context prohibited')
    env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env['DOCKER_BUILDKIT']='1'
    if command(['docker','context','show'],capture=True,env=env).strip()!='default':
        raise ValueError('Only local default Docker context is supported')
    return env


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['init','up','stop','down','status','probe','diagnostics','ci-clean'])
    p.add_argument('state_dir',type=Path)
    p.add_argument('--expected-policy',default='')
    a=p.parse_args()
    if not a.state_dir.is_absolute() or a.state_dir.is_symlink(): raise ValueError('Use an absolute private state directory')
    d=a.state_dir.resolve()
    if d==ROOT or ROOT in d.parents: raise ValueError('State directory must be outside the repository')
    if a.action=='init': init(d); return
    values=read_state(d); env=clean_env()
    project='bp-hei06a2-'+values['STAGE_INSTANCE'][:16]
    compose=['docker','compose','--project-name',project,'--project-directory',str(BASE),'--env-file',str(d/'staging.env'),'-f',str(BASE/'compose.yml')]
    def run(*args,capture=False):return command(compose+list(args),capture=capture,env=env)
    if a.action=='up':
        if head()!=values['STAGE_COMMIT'] or command(['git','status','--porcelain'],capture=True).strip():
            raise ValueError('Use the exact clean candidate checkout; no automatic upgrades')
        for directory in (ROOT, ROOT/'backend', ROOT/'frontend', BASE):
            for path in directory.glob('.env*'):
                if path.is_file() and path.name not in {'.env.example','.env.sample','.env.template'}:
                    raise ValueError('Use a dedicated checkout without environment files')
        run('build'); run('up','-d','--wait','staging-postgres')
        run('run','--rm','--no-deps','api','bootstrap')
        run('up','-d','--wait','--no-build','api','bp-hermes','frontend')
    elif a.action=='stop': run('stop','frontend','api','bp-hermes')
    elif a.action=='down': run('down','--remove-orphans')  # NO --volumes
    elif a.action=='status': run('ps')
    elif a.action=='probe':
        # Verify actual runtime topology before invoking the probe, not only YAML.
        import json
        def inspect(service):
            cid=run('ps','-q',service,capture=True).strip()
            if not cid or '\n' in cid: raise ValueError('Expected one active container')
            return json.loads(command(['docker','inspect',cid],capture=True,env=env))[0]
        for name in ('staging-postgres','api','bp-hermes','frontend'):
            obj=inspect(name); nets=set(obj['NetworkSettings']['Networks']); ports=obj['NetworkSettings']['Ports'] or {}
            want={project+'_private'} | ({project+'_ingress'} if name=='frontend' else set())
            if nets!=want or not obj['State']['Running']: raise ValueError('Unexpected network or service state')
            bindings=[(key,b) for key,items in ports.items() for b in (items or [])]
            if name=='frontend':
                if bindings!=[('8080/tcp',{'HostIp':'127.0.0.1','HostPort':'18082'})]: raise ValueError('Unexpected frontend binding')
            elif bindings: raise ValueError('Private service has host ports')
            if name in ('api','bp-hermes') and obj['Config']['User']!='10001:10001': raise ValueError('Private app must be non-root')
        if command(['docker','network','inspect',project+'_private','--format','{{.Internal}}'],capture=True,env=env).strip()!='true':
            raise ValueError('Private network not internal')
        run('exec','-T','api','python','/opt/stage/probe.py',a.expected_policy)
    elif a.action=='diagnostics':
        # Only this Compose project's known services, and only sanitized fields.
        import json
        from startup_evidence import collect_events
        report={'schema':'hei06a2-startup-evidence/1','candidate_commit':values['STAGE_COMMIT'],'production_readiness':'CLOSED','services':{}}
        for service in ('staging-postgres','api','bp-hermes','frontend'):
            info={'present':False}
            report['services'][service]=info
            try:
                cid=run('ps','-a','-q',service,capture=True).strip()
                if not cid:continue
                if not re.fullmatch(r'[0-9a-f]{12,64}',cid):raise ValueError('Unexpected container identifier')
                obj=json.loads(command(['docker','inspect',cid],capture=True,env=env))[0]
                if obj['Config']['Labels'].get('com.docker.compose.project')!=project or obj['Config']['Labels'].get('com.docker.compose.service')!=service:
                    raise ValueError('Unexpected container scope')
                state=obj['State']; health=state.get('Health') or {}
                info.update(present=True,running=state['Running'],exit_code=state['ExitCode'],oom_killed=state['OOMKilled'],restart_count=obj['RestartCount'],health=health.get('Status','none'),failing_streak=health.get('FailingStreak',0))
                info['health_events']=collect_events('\n'.join(x.get('Output','') for x in health.get('Log',[])))
                # Raw logs may contain credentials/SQL/etc. Never emit them.
                logs=subprocess.run(['docker','logs','--tail','300',cid],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)
                info['startup_events']=collect_events(logs.stdout)
            except (ValueError,KeyError,IndexError,OSError,subprocess.CalledProcessError) as exc:
                info['collection_error']=type(exc).__name__
        print(json.dumps(report,sort_keys=True))
    elif a.action=='ci-clean':
        # Volume deletion is ONLY available to disposable hosted CI under RUNNER_TEMP.
        if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or not os.environ.get('RUNNER_TEMP') or Path(os.environ['RUNNER_TEMP']).resolve() not in d.parents:
            raise ValueError('Volume deletion prohibited outside hosted disposable CI')
        run('down','--volumes','--remove-orphans')
        for args in (['ps','-aq'],['volume','ls','-q'],['network','ls','-q']):
            if command(['docker',*args,'--filter','label=com.docker.compose.project='+project],capture=True,env=env).strip():
                raise ValueError('CI resources remain')

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        # Do not print command output or environment/secret values.
        print('Staging command failed: '+type(exc).__name__,file=sys.stderr);sys.exit(2)
