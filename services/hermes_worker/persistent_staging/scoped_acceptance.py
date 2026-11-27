"""Hosted-CI acceptance against the actual persistent Compose topology.
Offline lane never calls a model. Real lane uses the existing staged SDK.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error

from manage import BASE, ROOT, read_state
from scoped_policy import SCOPE, KEY, require, ScopedDenied


class ProbeFailure(RuntimeError):
    def __init__(self, action, report):
        super().__init__(action)
        self.evidence={k:report[k] for k in ('action','status','exception_type','reason','locations') if k in report}


def cli(script, action, state, *args, expect=True, model=False):
    env=dict(os.environ)
    if not model:env.pop(KEY,None)
    r=subprocess.run([sys.executable,str(BASE/script),action,str(state),*args],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if script=='manage.py':
        require(r.returncode==0,'foundation_command_failed');return {}
    lines=r.stdout.splitlines();require(bool(lines),'missing_report')
    out=json.loads(lines[-1]);require(out.get('schema')=='hei06a2b-scoped-simulation/1','wrong_report')
    if expect is True:
        if r.returncode!=0 or out.get('status')!='PASS':raise ProbeFailure(action,out)
    else:
        if r.returncode==0 or out.get('status')!='FAIL' or out.get('reason')!=expect:raise ProbeFailure(action,out)
    return out


def inspector(state, revision):
    values=read_state(state)
    base='http://127.0.0.1:18082'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(path,*,data=None,token=None,expected=200):
        headers={'Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path,data=data,headers=headers)
        try:
            with opener.open(req,timeout=15) as r:
                require(r.status==expected,'unexpected_http_status');return json.load(r)
        except urllib.error.HTTPError as exc:
            require(exc.code==expected,'unexpected_http_error');return {}
    auth=request('/api/v1/auth/login',data=urllib.parse.urlencode({'username':'staging-admin@example.invalid','password':values['STAGE_ADMIN_PASSWORD']}).encode())
    require(auth['role']=='superadmin','wrong_staff_role')
    token=auth['access_token'];path='/api/v1/ai/hermes/staff/conversations/'+SCOPE['conversation_id']+'/context?'
    scope={k:v for k,v in SCOPE.items() if k!='conversation_id'}
    result=request(path+urllib.parse.urlencode(scope),token=token)
    require(result['revision']==revision and result['has_state']==bool(revision) and result['live_routing_enabled'] is False,'inspector_mismatch')
    request(path+urllib.parse.urlencode({**scope,'company_id':'not-authorized'}),token=token,expected=404)
    selector=request('/api/v1/ai/hermes/engine',token=token)
    require(selector['active_sales_engine']=='langgraph' and selector['hermes_live_ready'] is False,'production_selector_changed')


def evaluate(state, report, with_model):
    def s(action,*args,expect=True,model=False):
        report['checkpoint']=action
        result=cli('scoped_manage.py',action,state,*args,expect=expect,model=model)
        if expect is not True:report['negative_checks']+=1
        return result
    def enqueue(event,file,expect=True):return s('enqueue','--event-id',event,'--message-file',str(file),expect=expect)
    def process(event,expect=True,model=False):return s('process','--event-id',event,*(['--model'] if model else []),expect=expect,model=model)
    with tempfile.TemporaryDirectory(dir=state.parent) as t:
        msg=Path(t)/'synthetic.txt';msg.write_text('What is the name of this project? Please check the project overview.',encoding='utf-8')
        other=Path(t)/'other.txt';other.write_text('Tell me about Van Buren.',encoding='utf-8')
        first='hermes:staged:offline-first';second='hermes:staged:offline-second'
        s('init');s('init');enqueue(first,msg,'grant_closed')
        g=s('grant');s('grant',expect='revoke_previous_grant_first');enqueue(first,msg);require(enqueue(first,msg)['replayed'],'duplicate_enqueue')
        enqueue(first,other,'event_collision');enqueue('sms:real',msg,'invalid_event');enqueue(second,other)
        process(second,'fifo_required');process(first,'model_key_missing') # FIFO and absent model key
        a=s('status');require(a['queue_counts']=={'pending':2} and a['runs']==a['replies']==a['simulation_receipts']==0,'offline_queue_mismatch')
        report['checkpoint']='recreate_with_grant'
        cli('manage.py','down',state);cli('manage.py','up',state)
        b=s('status');require(a==b,'grant_or_queue_not_persisted')
        inspector(state,0);report['checks']['grant_and_queue_persisted']=True
        s('revoke');process(first,'grant_closed');enqueue('hermes:staged:revoked',msg,'grant_closed')
        b=s('status');require(not b['active'] and b['queue_counts']=={'revoked':2} and b['runs']==0,'revocation_failed')
        report['checks']['offline_authorization_and_revocation']=True
        report['checks']['offline_no_model_or_effects']=True
        if with_model:
            require(bool(os.environ.get(KEY)),'model_secret_missing')
            s('grant');e1='hermes:staged:model-first';e2='hermes:staged:model-second'
            enqueue(e1,msg);enqueue(e2,other)
            one=process(e1,model=True);require(one['revision']==1 and not one['replayed'],'first_receipt')
            again=process(e1);require(again['replayed'] and all(again[k]==one[k] for k in ('run_id','reply_id','revision')),'replay_changed')
            two=process(e2,model=True);require(two['revision']==2 and two['run_id']!=one['run_id'],'second_receipt')
            c=s('status');require(c['queue_counts']=={'completed':2,'revoked':2} and c['runs']==c['replies']==c['simulation_receipts']==2,'model_receipt_counts')
            inspector(state,2);report['checks']['real_sdk_and_inspector']=True
            report['checks']['exact_replay_no_inference']=True
            s('revoke');process(e2,'grant_closed');require(not s('status')['active'],'grant_still_active')
            report['checks']['real_grant_revoked']=True
        report['checks']['commercial_effects_zero']=True
        report['checkpoint']='complete';report['status']='PASS'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('state',type=Path);p.add_argument('--model',action='store_true');a=p.parse_args()
    report={'schema':'hei06a2b-scoped-acceptance/1','status':'FAIL','candidate_commit':read_state(a.state)['STAGE_COMMIT'],'checkpoint':'start','negative_checks':0,'checks':{},'real_inference':'REQUESTED' if a.model else 'NOT_RUN','normal_live_worker_routing':'NOT_RUN','real_provider_acceptance':'NOT_RUN','production_readiness':'CLOSED'}
    try:
        require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted' and bool(os.environ.get('RUNNER_TEMP')) and Path(os.environ['RUNNER_TEMP']).resolve() in a.state.resolve().parents,'hosted_ci_only')
        evaluate(a.state,report,a.model)
        if a.model:report['real_inference']='PASS'
    except Exception as exc:
        report['exception_type']=type(exc).__name__
        if isinstance(exc,ScopedDenied):report['reason']=str(exc)
        if isinstance(exc,ProbeFailure):report['runtime_failure']=exc.evidence
    print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)
