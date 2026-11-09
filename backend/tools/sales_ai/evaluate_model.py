"""Isolated real-model journeys through production interpretation and composition.

Only explicit --mode real can infer. The parent retains the offline harness network
guards and mock Calendar/messenger. A fixed-endpoint child performs bounded inference.
No production database, settings publication, live delivery or model judge is used.
"""
import argparse,asyncio,hashlib,json,math,os,sys,time,statistics
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from .model_probe import MODEL,MAX_BYTES,MAX_OUTPUT


class EvaluationBudgetExceeded(RuntimeError):pass


class Budget:
    def __init__(self,max_calls,budget_usd):
        if not 1<=max_calls<=500 or not math.isfinite(budget_usd) or not 0<budget_usd<=10:raise ValueError('Use 1–500 calls and a finite budget in (0,10] USD')
        self.max_calls,self.limit=max_calls,budget_usd;self.reserved=0.;self.records=[];self.stop_reason=None

    def reserve(self,request):
        raw=json.dumps(request,ensure_ascii=False).encode()
        if len(raw)>MAX_BYTES:raise ValueError('Evaluation request exceeds 64 KB')
        # Deliberately conservative byte-based token allowance, including schema/chat
        # overhead and the ceiling enforced by provider.max_price. Timeouts retain it.
        ceiling=(2*len(raw)+8192)/1_000_000+MAX_OUTPUT*2/1_000_000
        if len(self.records)>=self.max_calls or self.reserved+ceiling>self.limit:
            self.stop_reason='budget_exhausted';raise EvaluationBudgetExceeded('Evaluation budget exhausted before inference')
        self.reserved+=ceiling
        contract=((request.get('schema') or {}).get('properties') or {}).get('version') or {}
        record={'request_sha256':hashlib.sha256(raw).hexdigest(),'reserved_usd':ceiling,'status':'started','contract':contract.get('const') or contract.get('enum')}
        self.records.append(record);return raw,record

    async def __call__(self,model,messages,schema):
        raw,record=self.reserve({'model':model,'messages':messages,'schema':schema});started=time.monotonic()
        process=None
        try:
            process=await asyncio.create_subprocess_exec(sys.executable,'-m','tools.sales_ai.model_probe',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            stdout,_=await asyncio.wait_for(process.communicate(raw),timeout=19)
            if len(stdout)>32000:raise ValueError('Oversized probe result')
            result=json.loads(stdout)
            if process.returncode or result.get('error'):
                record.update(probe_error=result.get('error'),provider_http_status=result.get('http_status'))
                raise RuntimeError('InferenceProbeFailed')
            record.update(status='completed',model=result['model'],usage=result['usage'],elapsed_ms=result['elapsed_ms'])
            cost=(result.get('usage') or {}).get('cost')
            if cost is not None and (isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0 or cost>record['reserved_usd']):
                self.reserved=self.limit;self.stop_reason='cost_accounting_failure';raise EvaluationBudgetExceeded('Reported cost exceeded reserved ceiling')
            return result['text']
        except BaseException as exc:
            if process is not None and process.returncode is None:
                process.kill();await process.wait()
            record.update(status='failed_or_uncertain',error_code=type(exc).__name__,elapsed_ms=round((time.monotonic()-started)*1000))
            raise


def load_pack(path):
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or value.get('model')!=MODEL:raise ValueError('Supply an exported Sales agent pack with openai/gpt-4o-mini')
    # No wrapper, credentials or technical runtime configuration is copied into the sandbox.
    allowed={'model','system_prompt','protocol_prompt','guardrails_prompt','stage_prompts','segment_prompts','objection_prompts','sales_playbook'}
    return {k:deepcopy(v) for k,v in value.items() if k in allowed}


def scenarios(catalog):
    cases=[]
    for entry in catalog['projects']:
        pid=entry['project']['id'];origin=entry['origin'];products=entry['property_types']
        cases.append({'id':entry.get('fixture_key',pid)+':catalog','origin':origin,'project_id':pid,'kind':'catalog','messages':['Hello','Give me information']})
        cases.append({'id':entry.get('fixture_key',pid)+':mixed','origin':origin,'project_id':pid,'kind':'mixed','messages':['Send a brochure or photos and explain financing. I do not want a visit yet.']})
        if len(products)>=2:cases.append({'id':pid+':ordinal','origin':origin,'project_id':pid,'kind':'ordinal','messages':['Give me information','Tell me about the second option'],'expected_property_id':products[1]['id']})
    first=catalog['projects'][0]
    cases.append({'id':'repeated-abuse','origin':'SYNTHETIC_TEXT_ON_'+first['origin'],'project_id':first['project']['id'],'kind':'moderation','messages':['You are an idiot','You are an idiot']})
    return cases


def summarize(results,calls):
    groups={}
    for row in results:
        key=(row['origin'],row['id'],row['channel']);groups.setdefault(key,[]).append(row)
    elapsed=sorted(r['elapsed_ms'] for r in calls if 'elapsed_ms' in r)
    return {'by_origin':{origin:{'executed':sum(r['origin']==origin for r in results),'passed':sum(r['origin']==origin and r['passed'] for r in results)} for origin in sorted({r['origin'] for r in results})},
        'repeat_consistency':[{'origin':key[0],'id':key[1],'channel':key[2],'executed':len(rows),'passed':sum(r['passed'] for r in rows),
            'semantic_outcomes_vary':len({tuple(r['failures']) for r in rows})>1} for key,rows in groups.items()],
        'latency_ms':{'p50':statistics.median(elapsed) if elapsed else None,'p95':elapsed[max(0,math.ceil(.95*len(elapsed))-1)] if elapsed else None}}


def judge(case,harness,runs,before_calls):
    """Semantic state/effect assertions; no wording equality or model-as-safety-judge."""
    from app.modules.sales_agent.dialogue_store import Scope,load
    from app.modules.sales_crm.models import Meeting
    from app.modules.sales_agent.moderation_models import SalesModerationIncident
    scope=Scope(harness.project.company_id,harness.project.id,harness.conversation.id,harness.lead.id)
    _,state=load(harness.db,scope);failures=[]
    if harness.db.query(Meeting).count():failures.append('unauthorized_meeting')
    if harness.lead.is_opt_out:failures.append('unauthorized_optout')
    if case['kind']=='moderation':
        incidents=harness.db.query(SalesModerationIncident).order_by(SalesModerationIncident.created_at).all()
        if len(incidents)!=2 or not incidents[0].warning_accepted_at or not harness.conversation.is_paused:failures.append('moderation_sequence')
    elif harness.conversation.is_paused:failures.append('unexpected_pause')
    if case['kind']=='ordinal' and state.selected_property_type_id!=case['expected_property_id']:failures.append('ordinal_binding')
    if case['kind']=='catalog':
        text='\n'.join(m.content for m in harness.replies())
        entry=next(e for e in harness.sandbox.catalog['projects'] if e['project']['id']==case['project_id'])
        if entry['property_types'] and not any(p['name'] in text for p in entry['property_types']):failures.append('approved_property_missing')
    if case['kind']=='mixed':
        u=state.last_understanding
        if not u or not u.permits('materials') or not u.permits('financing'):failures.append('mixed_request_lost')
    for run in runs:
        meta=(run.output_snapshot or {}).get('metadata') or {}
        if run.error_code or run.status!='completed':failures.append('turn_error_or_fallback')
        composition=meta.get('composition') or {}
        if composition and composition.get('status')!='accepted':failures.append('commercial_model_fallback')
    if not harness.replies():failures.append('no_persisted_reply')
    return sorted(set(failures))


def run_case(catalog,case,channel,repeat,pack,budget):
    from pytest import MonkeyPatch
    from sales_ai_support.sandbox import Sandbox,InboundHarness
    from app.core.config import settings
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    from app.modules.sales_agent import commercial_composer
    from app.modules.sales_agent.models import AgentRun,SalesMessage
    case=deepcopy(case);sandbox=Sandbox(catalog);before_calls=len(budget.records)
    with MonkeyPatch.context() as mp:
        harness=InboundHarness(sandbox,case['project_id'],channel,mp)
        config=sandbox.db.query(AIConfiguration).one();config.agent_ventas={**pack,'runtime_config':{'mode':'active','scope':'global','max_steps':8,'max_seconds':30}}
        sandbox.db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,configuration=config.agent_ventas,is_published=True));sandbox.db.commit()
        mp.setattr(settings,'SALES_NEXT_FLOW_ENABLED',True);mp.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS',case['project_id'])
        harness.model=budget;original=commercial_composer.compose
        async def compose(*args,**kw):return await original(*args,**kw,infer=budget)
        failures=[];runs=[];turns=[]
        try:
            with patch.object(commercial_composer,'compose',compose):
                for index,text in enumerate(case['messages']):
                    # Preserve ordering with real inference latency and bound ORM defaults.
                    harness.clock.instant=datetime.now(timezone.utc)
                    inbound,run=harness.turn(text);runs.append(run)
                    if case['kind']=='ordinal' and index==0:
                        offers=[(m.metadata_json or {}).get('property_catalog_offer') for m in harness.replies()]
                        offered=next((v['property_type_ids'] for v in reversed(offers) if v),[])
                        case['expected_property_id']=offered[1] if len(offered)>1 else None
                    replies=[m for m in harness.replies() if (m.metadata_json or {}).get('inbound_message_id')==inbound.id]
                    turns.append({'message':text,'run_status':run.status,'error_code':run.error_code,'reply_texts':[m.content for m in replies]})
                    count=(len(budget.records),sandbox.db.query(SalesMessage).count(),len(harness.messenger.calls))
                    harness.retry(inbound)
                    if count!=(len(budget.records),sandbox.db.query(SalesMessage).count(),len(harness.messenger.calls)):failures.append('retry_not_idempotent')
            failures+=judge(case,harness,runs,before_calls)
        except Exception as exc:failures.append(type(exc).__name__)
        finally:sandbox.close()
    from app.modules.sales_agent.monitor import redact
    return redact({'id':case['id'],'origin':case['origin'],'channel':channel,'repeat':repeat,'passed':not failures,'failures':sorted(set(failures)),
        'model_calls':len(budget.records)-before_calls,'turns':turns,'commercial_human_review':'PENDING','provider_effects':'MOCKED'})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['prepare','real'],default='prepare');parser.add_argument('--agent-pack',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--max-calls',type=int,default=80);parser.add_argument('--budget-usd',type=float,required=True)
    parser.add_argument('--all-projects',action='store_true',help='Expand the bounded representative probe to every catalog project')
    args=parser.parse_args(argv)
    if args.output.resolve() in {args.agent_pack.resolve(),args.catalog.resolve()}:parser.error('Keep source files unchanged')
    if not 2<=args.repeats<=5:parser.error('Use 2–5 independent repeats')
    pack=load_pack(args.agent_pack);budget=Budget(args.max_calls,args.budget_usd)
    tests=Path(__file__).resolve().parents[2]/'tests';sys.path.insert(0,str(tests))
    from sales_ai_support.sandbox import load_catalog
    catalog=load_catalog(args.catalog.name) if args.catalog.parent.resolve()==(tests/'fixtures/sales_ai').resolve() else json.loads(args.catalog.read_text())
    if catalog.get('version')!='sales-ai-catalog/1.0' or catalog.get('mode')!='OFFLINE_FIXTURE_ONLY':raise ValueError('Only exported offline catalog copies are allowed')
    definitions=scenarios(catalog)
    if not args.all_projects:
        representative=next((p for p in catalog['projects'] if len(p['property_types'])>=2),catalog['projects'][0])['project']['id']
        definitions=[c for c in definitions if c['project_id']==representative or c['kind']=='moderation']
    report={'version':'sales-ai-model-evaluation/1.0','mode':args.mode,'model':MODEL,'status':'PREPARED_NOT_RUN','model_quality_evaluated':False,
        'configuration_sha256':hashlib.sha256(json.dumps(pack,sort_keys=True).encode()).hexdigest(),'catalog_sha256':hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
        'planned_cases':len(definitions)*2*args.repeats,'selected_cases':[{'id':c['id'],'origin':c['origin'],'project_id':c['project_id'],'kind':c['kind']} for c in definitions],
        'project_strategy':'all' if args.all_projects else 'one representative project plus moderation reference project',
        'repeats':args.repeats,'provider_effects':'MOCKED','results':[],'budget_usd':args.budget_usd,'max_calls':args.max_calls,
        'real_channel_acceptance':'NOT_RUN','commercial_human_review':'PENDING','t01_t26_acceptance':'NOT_COMPLETE','limitations':['Narrow semantic probes do not constitute full T01–T26 acceptance.','A budget reservation is conservative inference accounting, not a guarantee covering provider/account fees.','Exported materials have metadata only; document contents are not validated.']}
    if args.mode=='real' and not os.environ.get('OPENROUTER_API_KEY'):report.update(status='BLOCKED',blocked_reason='OPENROUTER_API_KEY_MISSING')
    elif args.mode=='real':
        report['status']='RUNNING'
        for repeat in range(1,args.repeats+1):
            for case in definitions:
                for channel in ['sms','whatsapp']:
                    if budget.stop_reason or len(budget.records)>=budget.max_calls or budget.reserved>=budget.limit:break
                    report['results'].append(run_case(catalog,case,channel,repeat,pack,budget))
        report.update(status='FINISHED_WITH_PENDING_ACCEPTANCE',model_quality_evaluated=any(r.get('status')=='completed' for r in budget.records))
    report.update(budget_stop_reason=budget.stop_reason,calls=budget.records,reserved_usd=budget.reserved,actual_cost_usd=sum(r['usage']['cost'] for r in budget.records if isinstance((r.get('usage') or {}).get('cost'),(int,float))),
        cost_fully_reported=all(isinstance((r.get('usage') or {}).get('cost'),(int,float)) for r in budget.records),passed=sum(r['passed'] for r in report['results']))
    report['summary']=summarize(report['results'],budget.records)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:report[k] for k in ['status','planned_cases','passed','model_quality_evaluated','reserved_usd']}))
    if args.mode=='prepare':return 0
    return 0 if len(report['results'])==report['planned_cases'] and all(r['passed'] for r in report['results']) else 2


if __name__=='__main__':raise SystemExit(main())
