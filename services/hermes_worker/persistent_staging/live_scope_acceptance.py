"""Hosted CI orchestration of the scoped live-inbound acceptance lane.
The normal API is stopped while the one-shot worker owns the actual queue.
The SDK is private and only the real-model lane receives temporary egress.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error

from manage import BASE, ROOT, clean_env, read_state, head
from live_scope_policy import SCOPE, MARKER, KEY
from scoped_policy import require, ScopedDenied


class PhaseFailure(RuntimeError):
    def __init__(self, report):
        super().__init__('live worker phase failed')
        keys=('action','status','checkpoint','exception_type','reason','locations','job_status','job_error_code','invocations','simulated_sends','worker_failure')
        self.evidence={k:report[k] for k in keys if k in report}


def invoke(args,env,*,check=True):
    r=subprocess.run(args,cwd=ROOT,env=env,text=True,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=240)
    if check and r.returncode:raise RuntimeError('isolated command failed')
    return r


def inspector(values,revision):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(path,*,data=None,token=None,expected=200):
        headers={'Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request('http://127.0.0.1:18082'+path,data=data,headers=headers)
        try:
            with opener.open(req,timeout=15) as response:
                require(response.status==expected,'live_inspector_http_status');return json.load(response)
        except urllib.error.HTTPError as exc:
            require(exc.code==expected,'live_inspector_http_error');return {}
    auth=request('/api/v1/auth/login',data=urllib.parse.urlencode({'username':'staging-admin@example.invalid','password':values['STAGE_ADMIN_PASSWORD']}).encode())
    require(auth['role']=='superadmin','live_inspector_staff_role')
    token=auth['access_token'];scope={k:v for k,v in SCOPE.items() if k!='conversation_id'}
    path='/api/v1/ai/hermes/staff/conversations/'+SCOPE['conversation_id']+'/context?'
    response=request(path+urllib.parse.urlencode(scope),token=token)
    require(response['revision']==revision and response['has_state'] is True and response['live_routing_enabled'] is False,'live_inspector_state_mismatch')
    request(path+urllib.parse.urlencode({**scope,'company_id':'outside-scope'}),token=token,expected=404)
    selector=request('/api/v1/ai/hermes/engine',token=token)
    require(selector['active_sales_engine']=='langgraph' and selector['hermes_live_ready'] is False,'live_global_gate_changed')


def evaluate(state,report,model):
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
            and bool(os.environ.get('RUNNER_TEMP')) and Path(os.environ['RUNNER_TEMP']).resolve() in state.resolve().parents,'live_hosted_ci_only')
    require(state.is_absolute() and not state.is_symlink(),'live_invalid_state_path')
    state=state.resolve();values=read_state(state)
    require(head()==values['STAGE_COMMIT'],'live_candidate_changed')
    env=clean_env();require(not invoke(['git','status','--porcelain'],env).stdout.strip(),'live_candidate_not_clean')
    key=os.environ.get(KEY,'');require(bool(key and key!='test-only') if model else not key,'live_model_key_mode_mismatch')
    project='bp-hei06a2-'+values['STAGE_INSTANCE'][:16]
    compose=['docker','compose','--project-name',project,'--project-directory',str(BASE),'--env-file',str(state/'staging.env'),'-f',str(BASE/'compose.yml')]
    network=project+'_live_egress';name=project+'-scoped-live-sdk';created_network=False;started_sdk=False
    def docker(*args,check=True,custom_env=None):return invoke(['docker',*args],custom_env or env,check=check)
    def run(*args,check=True,custom_env=None):return invoke(compose+list(args),custom_env or env,check=check)
    def phase(action,*args,case=None):
        report['checkpoint']=action+(':'+case if case else '')
        r=run('run','--rm','-T','--no-deps','--entrypoint','python','-e','HEI06A2_LIVE_ACCEPTANCE='+MARKER,'api','/opt/stage/live_scope_runtime.py',action,*args,check=False)
        lines=r.stdout.splitlines();require(bool(lines),'live_missing_phase_report')
        try:out=json.loads(lines[-1])
        except (ValueError,TypeError):raise ScopedDenied('live_invalid_phase_report') from None
        require(out.get('schema')=='hei06a2b2-live-worker/1','live_wrong_phase_schema')
        if r.returncode or out.get('status')!='PASS':raise PhaseFailure(out)
        if action=='run':report['http_negative_executions']+=out.get('http_negative_checks',0)
        return out
    try:
        report['checkpoint']='isolate_existing_services'
        require(docker('network','inspect',project+'_private','--format','{{.Internal}}').stdout.strip()=='true','live_network_not_private')
        # The normal API worker must not race with the one-shot inbound lane.
        run('stop','frontend','api','bp-hermes')
        for service in ('api','bp-hermes'):
            cid=run('ps','-a','-q',service).stdout.strip()
            require(cid and '\n' not in cid,'live_original_container_missing')
            require(docker('inspect',cid,'--format','{{.State.Running}}').stdout.strip()=='false','live_original_worker_not_stopped')
        seed=phase('init');report['checks']['attested_fixture_and_grant']=seed['initialized'] and seed['grant_active']
        report['checkpoint']='start_private_scoped_sdk'
        args=['run','-d','--no-deps','--use-aliases','--name',name,'--entrypoint','python','-e','HEI06A2_LIVE_ACCEPTANCE='+MARKER]
        sdk_env=dict(env)
        if model:
            sdk_env[KEY]=key;args+=['-e',KEY]
        args+=['bp-hermes','/opt/stage/live_scope_runtime.py','sdk']+(['--model'] if model else [])
        run(*args,custom_env=sdk_env);started_sdk=True
        obj=json.loads(docker('inspect',name).stdout)[0]
        require(obj['State']['Running'] and obj['Config']['User']=='10001:10001' and obj['Config']['Image']=='bp-hei06a2-sdk:'+values['STAGE_COMMIT'] and obj['Config']['Labels'].get('com.docker.compose.project')==project,'live_wrong_sdk_container')
        require(set(obj['NetworkSettings']['Networks'])=={project+'_private'} and not any((obj['NetworkSettings']['Ports'] or {}).values()),'live_sdk_network_or_port')
        if model:
            docker('network','create','--label','com.docker.compose.project='+project,network);created_network=True
            docker('network','connect',network,name)
            info=json.loads(docker('network','inspect',network).stdout)[0]
            require(len(info['Containers'])==1 and next(iter(info['Containers'].values()))['Name']==name,'live_egress_not_sdk_only')
        report['checks']['private_sdk_topology']=True
        def one(action,case):return phase(action,'--case',case,case=case)
        first=one('enqueue','first');require(first['job_status']=='pending' and not first['replayed'],'live_first_enqueue')
        require(one('enqueue','first')['replayed'],'live_duplicate_enqueue')
        first=one('run','first');require(first['revision']==1 and first['invocations']==first['simulated_sends']==1,'live_first_receipt')
        report['checkpoint']='restart_private_sdk'
        docker('restart','--time','5',name)
        report['checks']['sdk_restarted_before_replay']=True
        before=one('requeue','first');require(before['run_id']==first['run_id'],'live_requeue_changed_run')
        replay=one('run','first')
        fields=('run_id','reply_id','revision','invocations','simulated_sends','policy_id')
        require(all(first[k]==replay[k] for k in fields),'live_replay_changed_receipt')
        report['checks']['actual_worker_replay_no_duplicate']=True
        one('enqueue','second');second=one('run','second')
        require(second['revision']==2 and second['run_id']!=first['run_id'] and second['policy_id']==first['policy_id'],'live_second_receipt')
        report['checks']['two_actual_inbound_jobs_and_receipts']=True
        one('enqueue','revoked');require(phase('revoke')['grant_active'] is False,'live_revoke_failed')
        denied=one('run','revoked');require(denied['revoked_job_review'],'live_revoked_router_not_denied')
        report['checks']['revoked_job_review_no_fallback']=True
        final=phase('status');report['counts']=final['counts'];report['revision']=final['revision'];report['commercial_effect_rows']=final['commercial_effect_rows']
        report['checks']['no_native_or_scheduled_effects']=True
        # Close the temporary SDK before restoring the normal closed API.
        report['checkpoint']='restore_closed_topology'
        docker('rm','-f',name);started_sdk=False
        if created_network:docker('network','rm',network);created_network=False
        run('up','-d','--wait','--no-build','api','bp-hermes','frontend')
        report['checkpoint']='inspector'
        inspector(values,2);report['checks']['inspector_state_and_global_gate']=True
        report['checks']['normal_closed_services_restored']=True
        report.update(status='PASS',checkpoint='complete',one_shot_live_worker='PASS',real_inference='PASS' if model else 'NOT_RUN')
    finally:
        # Only sanitized SDK diagnostic records, not raw provider/model logs.
        if started_sdk:
            r=docker('logs',name,check=False)
            lines=[]
            for line in (r.stdout+'\n'+r.stderr).splitlines():
                if not line.startswith('HEI06A2_LIVE_EVENT '):continue
                try:
                    x=json.loads(line.split('HEI06A2_LIVE_EVENT ',1)[1])
                    if x.get('phase')=='scoped_live_sdk_prepare' and x.get('status')=='FAIL':
                        lines.append({k:x[k] for k in ('phase','status','exception_type','locations') if k in x})
                except (ValueError,TypeError):continue
            if lines:report['sdk_diagnostics']=lines[-5:]
            docker('rm','-f',name,check=False)
        if created_network:docker('network','rm',network,check=False)
        # The canonical workflow always removes all CI resources, even on failure.


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('state',type=Path);p.add_argument('--model',action='store_true');a=p.parse_args()
    report={'schema':'hei06a2b2-live-acceptance/1','status':'FAIL','checkpoint':'start','checks':{},'http_negative_executions':0,'one_shot_live_worker':'NOT_RUN','continuous_api_worker_authorization':'NOT_RUN','real_inference':'REQUESTED' if a.model else 'NOT_RUN','real_provider_acceptance':'NOT_RUN','production_readiness':'CLOSED'}
    try:
        report['candidate_commit']=read_state(a.state)['STAGE_COMMIT'];evaluate(a.state,report,a.model)
    except Exception as exc:
        report['exception_type']=type(exc).__name__
        if isinstance(exc,ScopedDenied):report['reason']=str(exc)
        if isinstance(exc,PhaseFailure):report['phase_failure']=exc.evidence
        import traceback
        report['locations']=[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-6:]]
    print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)
