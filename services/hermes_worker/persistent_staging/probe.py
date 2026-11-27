"""Real HTTP control-plane and persistence checks. No live inference or provider effects."""
import json
import os
import sys
import time
from guard import validate, attest, require, ADMIN


def main(report):
    validate()
    import httpx
    from app.db.postgres import engine, SessionLocal
    import app.db.base
    from app.modules.sales_agent.models import AgentRun, SalesInboundJob, OutboundMessage
    from app.modules.sales_crm.models import Meeting
    from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
    require(live_hermes_ready() is False,'Gate unexpectedly open')
    with engine.connect() as c: attest(c)
    expected=sys.argv[1] if len(sys.argv)>1 else ''
    checks=report['checks']
    with httpx.Client(base_url='http://frontend:8080',trust_env=False,timeout=10) as c:
        report['checkpoint']='frontend_proxy'
        page=c.get('/login'); page.raise_for_status()
        require(page.headers.get('x-bp-environment')=='closed-persistent-staging' and "connect-src 'self'" in page.headers.get('content-security-policy',''),'Missing isolation header')
        require(c.get('/api/v1/health/version').json()['commit']==os.environ['APP_COMMIT_SHA'],'Proxy candidate mismatch')
        checks['frontend_same_origin']=True
        report['checkpoint']='local_auth'
        require(c.get('/api/v1/ai/hermes/global').status_code==401,'Anonymous policy access')
        login=c.post('/api/v1/auth/login',data={'username':ADMIN,'password':os.environ['FIRST_SUPERADMIN_PASSWORD']})
        login.raise_for_status(); require(login.json()['role']=='superadmin','Unexpected local role')
        c.headers['Authorization']='Bearer '+login.json()['access_token']
        checks['staff_auth']=True
        report['checkpoint']='blocked_routes'
        for method,path in [('POST','/api/v1/webhooks/telnyx/messaging'),('POST','/api/v1/sales-agent/live-leads'),('POST','/api/v1/sales-agent/conversations/stg-conversation/manual-message'),('GET','/api/v1/sales/calendar/google/callback'),('POST','/api/v1/auth/forgot-password')]:
            require(c.request(method,path).status_code==403,'External or effect route allowed')
        checks['effect_ingress_blocked']=True
        report['checkpoint']='policy'
        g=c.get('/api/v1/ai/hermes/global');g.raise_for_status();g=g.json()
        if expected:
            require(g['published_version_id']==expected and g['configuration']['enabled'] is True,'Published policy not preserved')
        elif not g['published_version_id']:
            cfg={**g['configuration'],'enabled':True,'enabled_tools':['get_project_overview','get_unit_details']}
            draft=c.post('/api/v1/ai/hermes/drafts',json={'configuration':cfg,'change_note':'Synthetic staging control-plane acceptance'})
            draft.raise_for_status(); published=c.post('/api/v1/ai/hermes/versions/'+draft.json()['id']+'/publish');published.raise_for_status();g=published.json()
        require(bool(g['published_version_id']),'No published policy')
        report['policy_id']=g['published_version_id'];checks['policy_published_or_preserved']=True
        report['checkpoint']='selector'
        selection=c.put('/api/v1/ai/hermes/engine',json={'active_sales_engine':'hermes','change_note':'Must remain closed'})
        require(selection.status_code==409 and selection.json()['detail']['code']=='HERMES_NOT_READY','Hermes selectable')
        actual=c.get('/api/v1/ai/hermes/engine');actual.raise_for_status()
        require(actual.json()['active_sales_engine']=='langgraph' and actual.json()['hermes_live_ready'] is False,'Wrong selector')
        checks['production_gate_closed']=True
        report['checkpoint']='inspector'
        context='/api/v1/ai/hermes/staff/conversations/stg-conversation/context'
        scope={'company_id':'stg-company','project_id':'stg-project','lead_id':'stg-lead'}
        require(c.get(context,params=scope).status_code==200,'Synthetic context unavailable')
        require(c.get(context,params={**scope,'company_id':'outside-scope'}).status_code==404,'Cross-scope context exposed')
        checks['inspector_scope_verified']=True
        report['checkpoint']='worker_health'
        for _ in range(30):
            health=c.get('/api/v1/health/sales')
            if health.status_code==200:break
            time.sleep(2)
        else: raise RuntimeError('Existing worker did not reach readiness')
        checks['sales_worker_scanning']=True
    report['checkpoint']='sdk_private'
    with httpx.Client(base_url='http://bp-hermes:8080',trust_env=False,timeout=5) as c:
        body={'job_id':'synthetic','run_id':'synthetic'}
        require(c.post('/internal/prepare',json=body).status_code==401,'Missing auth not rejected')
        require(c.post('/internal/prepare',json=body,headers={'Authorization':'Bearer invalid'}).status_code==401,'Wrong auth not rejected')
        h={'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']}
        require(c.post('/internal/prepare',json=body,headers=h).status_code==503,'Gate unexpectedly open')
        require(c.post('/internal/prepare',json={**body,'prompt':'not allowed'},headers=h).status_code==422,'Extra field accepted')
        require(c.get('/openapi.json').status_code==404,'SDK schema exposed')
    checks['private_sdk_closed']=True
    report['checkpoint']='zero_effects'
    with SessionLocal() as db:
        require(all(db.query(model).count()==0 for model in (AgentRun,SalesInboundJob,OutboundMessage,Meeting)),'Unexpected sales activity')
    checks['zero_sales_effects']=True
    report['checkpoint']='complete'; report['status']='PASS'

if __name__=='__main__':
    report={'schema':'hei06a2-closed-foundation/1','candidate_commit':os.environ.get('APP_COMMIT_SHA'),'status':'FAIL','checks':{},'production_readiness':'CLOSED','real_provider_acceptance':'NOT_RUN','real_inference':'NOT_RUN'}
    try:main(report)
    except Exception as exc:report['reason']=type(exc).__name__
    print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 2)
