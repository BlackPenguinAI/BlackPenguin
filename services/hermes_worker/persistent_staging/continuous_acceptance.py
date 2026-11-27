"""Hosted CI acceptance for a real continuously polling API worker.
No manual claim/handler calls. HTTP control uses the actual local staff JWT.
Only the dedicated SDK container receives optional internet egress.
"""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import urllib.error

from manage import BASE, ROOT, clean_env, read_state, head
from live_scope_acceptance import invoke, inspector
from live_scope_policy import SCOPE
from scoped_policy import require, ScopedDenied
from continuous_scope import MODEL_KEY, safe_failure

PREFIX='/api/v1/staging/hermes'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Control:
    def __init__(self):
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.token=None
    def request(self,path,*,method='GET',data=None,expected=200,auth=True):
        headers={'Accept':'application/json'}
        if auth and self.token:headers['Authorization']='Bearer '+self.token
        if data is not None:headers['Content-Type']='application/x-www-form-urlencoded'
        req=urllib.request.Request('http://127.0.0.1:18082'+path,data=data,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=15) as resp:
                require(resp.status==expected,'continuous_http_unexpected_status')
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            require(exc.code==expected,'continuous_http_unexpected_error');return {}
    def login(self,values):
        response=self.request('/api/v1/auth/login',method='POST',data=urllib.parse.urlencode({'username':'staging-admin@example.invalid','password':values['STAGE_ADMIN_PASSWORD']}).encode(),auth=False)
        require(response.get('role')=='superadmin','continuous_staff_role');self.token=response['access_token']
    def post(self,path,**kwargs):return self.request(PREFIX+path,method='POST',**kwargs)
    def get(self,path,**kwargs):return self.request(PREFIX+path,**kwargs)
    def wait_job(self,case,want,report):
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            row=self.get('/job/'+case)
            report['last_job_status']=row.get('job_status')
            if row.get('job_status')==want:return row
            if row.get('job_status') in {'review','failed','cancelled','processed'}:
                report['job_error_code']=row.get('error_code','other')
                raise ScopedDenied('continuous_job_unexpected_terminal_status')
            time.sleep(.75)
        raise ScopedDenied('continuous_worker_did_not_complete_job')


def evaluate(state,report,model):
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
            and bool(os.environ.get('RUNNER_TEMP')) and Path(os.environ['RUNNER_TEMP']).resolve() in state.resolve().parents,'continuous_hosted_ci_only')
    require(state.is_absolute() and not state.is_symlink(),'continuous_invalid_state_path')
    state=state.resolve();values=read_state(state);sha=values['STAGE_COMMIT']
    require(head()==sha,'continuous_candidate_changed')
    env=clean_env();require(not invoke(['git','status','--porcelain'],env).stdout.strip(),'continuous_candidate_not_clean')
    key=os.environ.get(MODEL_KEY,'');require(bool(key and key!='test-only') if model else not key,'continuous_key_mode_mismatch')
    project='bp-hei06a2-'+values['STAGE_INSTANCE'][:16]
    compose=['docker','compose','--project-name',project,'--project-directory',str(BASE),'--env-file',str(state/'staging.env'),'-f',str(BASE/'compose.yml')]
    active=compose+['-f',str(BASE/'continuous.compose.yml')]
    sdk_env=dict(env);sdk_env[MODEL_KEY]=key
    network=project+'_continuous_egress';network_created=False;sdk_id=None;derived_started=False
    def docker(*args,check=True):return invoke(['docker',*args],env,check=check)
    def run(*args,continuous=True,check=True):return invoke((active if continuous else compose)+list(args),sdk_env if continuous else env,check=check)
    def inspect(service,continuous=True):
        cid=run('ps','-q',service,continuous=continuous).stdout.strip()
        require(bool(cid) and '\n' not in cid,'continuous_missing_service')
        obj=json.loads(docker('inspect',cid).stdout)[0]
        require(obj['Config']['Labels'].get('com.docker.compose.project')==project and obj['Config']['Labels'].get('com.docker.compose.service')==service,'continuous_container_scope')
        return obj['Id'],obj
    def wait_worker(control):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            # A health response can legitimately be 503 during startup; the
            # actual inbound scan (not a fabricated heartbeat) must become ready.
            try: row=control.request('/api/v1/health/sales')
            except ScopedDenied:time.sleep(1);continue
            if row.get('status')=='ready' and row.get('worker_status')=='scanning':
                require(set(row.get('scans',{}))=={'inbound'} and row['scans']['inbound']['status']=='ok','continuous_worker_health_scope')
                return
            time.sleep(1)
        raise ScopedDenied('continuous_worker_health_not_ready')
    try:
        report['checkpoint']='build_native_staging_images'
        for service,root in [('api','/app'),('sdk','/opt/blackpenguin')]:
            docker('build','--build-arg','BASE_IMAGE=bp-hei06a2-'+service+':'+sha,'--build-arg','APP_ROOT='+root,'-t','bp-hei06a2-continuous-'+service+':'+sha,'-f',str(BASE/'continuous.Dockerfile'),str(BASE))
        report['checks']['certified_build_time_integration']=True
        report['checkpoint']='start_continuous_api_and_sdk'
        require(docker('network','inspect',project+'_private','--format','{{.Internal}}').stdout.strip()=='true','continuous_network_not_private')
        run('stop','frontend','api','bp-hermes',continuous=False)
        derived_started=True
        run('up','-d','--wait','--no-build','--no-deps','--force-recreate','api','bp-hermes','frontend')
        api_id,api=inspect('api');sdk_id,sdk=inspect('bp-hermes')
        for service,obj in [('api',api),('sdk',sdk)]:
            require(obj['State']['Running'] and obj['Config']['User']=='10001:10001' and obj['Config']['Image']=='bp-hei06a2-continuous-'+service+':'+sha,'continuous_wrong_image_or_user')
            require(set(obj['NetworkSettings']['Networks'])=={project+'_private'} and not any((obj['NetworkSettings']['Ports'] or {}).values()),'continuous_public_private_service')
        require(not any(v.startswith(MODEL_KEY+'=') for v in api['Config']['Env']),'continuous_key_exposed_to_api')
        if model:
            docker('network','create','--label','com.docker.compose.project='+project,network);network_created=True
            docker('network','connect',network,sdk_id)
            info=json.loads(docker('network','inspect',network).stdout)[0]
            require(set(info['Containers'])=={sdk_id},'continuous_egress_not_sdk_only')
        report['checks']['private_sdk_only_egress']=True
        control=Control();control.login(values)
        report['checkpoint']='verify_continuous_worker_health';wait_worker(control)
        report['checks']['actual_api_worker_scanning']=True
        report['checkpoint']='authenticated_scope'
        control.post('/grant',auth=False,expected=401)
        control.get('/job/first',auth=False,expected=401)
        control.post('/enqueue/outside-scope',expected=403)
        seed=control.post('/grant');require(seed['initialized'] and seed['grant_active'],'continuous_grant_creation')
        control.post('/grant',expected=409)
        r=run('exec','-T','api','python','-c',"from continuous_scope import request_checks; from live_scope_policy import Capability; print(request_checks(Capability('first','none','none')))")
        require(r.stdout.splitlines()[-1]=='6','continuous_sdk_negative_checks_missing')
        report['http_negative_checks']=6
        report['checks']['authenticated_scope_and_private_denials']=True
        report['checkpoint']='first_inbound_via_http'
        initial=control.post('/enqueue/first');require(initial['job_status']=='pending' and not initial['replayed'],'continuous_first_enqueue')
        # Duplicate request is a read-only idempotent lookup even if the actual
        # continuous worker has already claimed the event.
        first=control.wait_job('first','processed',report)
        require(first['revision']==1 and first['invocations']==first['simulated_sends']==1,'continuous_first_receipt')
        require(control.post('/enqueue/first')['replayed'],'continuous_duplicate_ingress')
        report['checks']['first_inbound_auto_processed']=True
        report['checkpoint']='restart_api_and_sdk'
        docker('restart','--time','10',api_id,sdk_id)
        # Wait for the actual API to come back through the existing Nginx proxy.
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:control.login(values);break
            except (OSError,ScopedDenied):time.sleep(1)
        else:raise ScopedDenied('continuous_api_restart_failed')
        wait_worker(control)
        _, restarted_sdk=inspect('bp-hermes')
        require(set(restarted_sdk['NetworkSettings']['Networks'])==({project+'_private',network} if model else {project+'_private'}),'continuous_sdk_network_after_restart')
        report['checks']['api_and_sdk_restarted']=True
        report['checkpoint']='replay_via_http'
        prior=control.post('/replay');require(prior['run_id']==first['run_id'],'continuous_replay_run_changed')
        replay=control.wait_job('first','processed',report)
        fields=('run_id','reply_id','revision','invocations','simulated_sends','policy_id')
        require(all(first[k]==replay[k] for k in fields) and replay['attempt_number']>first['attempt_number'],'continuous_replay_changed_receipt')
        report['checks']['actual_worker_replay_no_duplicate']=True
        report['checkpoint']='second_inbound_via_http'
        control.post('/enqueue/second');second=control.wait_job('second','processed',report)
        require(second['revision']==2 and second['run_id']!=first['run_id'] and second['policy_id']==first['policy_id'],'continuous_second_receipt')
        report['checks']['two_actual_inbound_jobs_and_receipts']=True
        report['checkpoint']='atomic_revoke_and_enqueue'
        # Third fixture is enqueued and the grant revoked in the same DB tx.
        # The real continuous worker cannot see an authorized pending third job.
        control.post('/enqueue/revoked');denied=control.wait_job('revoked','review',report)
        require(denied.get('error_code')=='HERMES_NOT_READY','continuous_revoked_route_not_denied')
        require(control.post('/revoke')['grant_active'] is False,'continuous_revocation_not_persistent')
        control.post('/enqueue/second',expected=409)
        report['checks']['revoked_job_review_no_fallback']=True
        final=control.get('/result');report['counts']=final['counts'];report['revision']=final['revision'];report['commercial_effect_rows']=final['commercial_effect_rows']
        report['runtime_modes']=final['runtime_modes']
        require(report['runtime_modes']==({'model':2} if model else {'offline':2}),'continuous_wrong_inference_mode')
        report['checks']['no_native_or_scheduled_effects']=True
        report['checkpoint']='inspector_continuous'
        inspector(values,2);report['checks']['inspector_state_and_global_gate']=True
        # Verify real provider webhook ingress remains closed in active mode.
        control.request('/api/v1/webhooks/telnyx/messaging',method='POST',expected=403)
        report['checks']['external_ingress_blocked']=True
        report['checkpoint']='restore_original_closed_services'
        if network_created:
            docker('network','disconnect',network,sdk_id);docker('network','rm',network);network_created=False
        run('stop','frontend','api','bp-hermes')
        run('up','-d','--wait','--no-build','--no-deps','--force-recreate','api','bp-hermes','frontend',continuous=False)
        derived_started=False
        for name in ('api','bp-hermes'):
            _,obj=inspect(name,continuous=False)
            require(obj['Config']['Image']=='bp-hei06a2-'+('api' if name=='api' else 'sdk')+':'+sha,'continuous_closed_image_not_restored')
        inspector(values,2)
        control.login(values);control.post('/grant',expected=403)
        report['checks']['closed_services_restored']=True
        report.update(status='PASS',checkpoint='complete',continuous_api_worker_authorization='PASS',real_inference='PASS' if model else 'NOT_RUN')
    finally:
        if derived_started:
            # Retain only allowlisted diagnostics, never raw container logs.
            from startup_evidence import collect_events
            for name in ('api','bp-hermes'):
                try:
                    r=run('logs','--no-color','--no-log-prefix','--tail','300',name,check=False)
                    report.setdefault('diagnostics',{})[name]=collect_events(r.stdout+'\n'+r.stderr)
                except Exception as exc:
                    report.setdefault('diagnostics',{})[name]={'collection_error':type(exc).__name__}
        if network_created:
            try:
                if sdk_id:docker('network','disconnect','-f',network,sdk_id,check=False)
                docker('network','rm',network,check=False)
            except Exception as exc:
                report['egress_cleanup_error']=type(exc).__name__
        # The canonical workflow performs CI cleanup even on failure.


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('state',type=Path);p.add_argument('--model',action='store_true');a=p.parse_args()
    report={'schema':'hei06a2b3-continuous-acceptance/1','status':'FAIL','checkpoint':'start','checks':{},'continuous_api_worker_authorization':'NOT_RUN','real_inference':'REQUESTED' if a.model else 'NOT_RUN','real_provider_acceptance':'NOT_RUN','production_readiness':'CLOSED'}
    try:
        report['candidate_commit']=read_state(a.state)['STAGE_COMMIT'];evaluate(a.state,report,a.model)
    except Exception as exc:
        report.update(safe_failure(exc))
        if isinstance(exc,ScopedDenied):report['reason']=str(exc)
    print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)
