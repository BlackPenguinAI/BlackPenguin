"""Compare two isolated run bundles; never call a provider or change a database."""
import argparse,json,statistics,zipfile
from pathlib import Path


def compare(reference,candidate):
    def load(path):
        with zipfile.ZipFile(path) as z:return json.loads(z.read('report.json')),json.loads(z.read('catalog.json'))
    a,ca=load(reference);b,cb=load(candidate)
    # Asset identities are generated independently in each disposable database.
    # Ignore ONLY this exact path; retain hashes, coverage and every other field.
    import copy
    def catalog(value):
        value=copy.deepcopy(value)
        for project in value.get('projects',[]):
            for prop in project.get('properties',[]):
                for asset in prop.get('resources',[]):asset.pop('asset_id',None)
        return value
    reasons=[]
    for key in ('commit','version','sales_model','configuration_sha256','configuration_version'):
        if not a.get(key) or a.get(key)!=b.get(key):reasons.append('mismatch:'+key)
    if catalog(ca)!=catalog(cb):reasons.append('mismatch:synthetic_catalog')
    keys=lambda r:[c.get('case') for c in r.get('cases',[])]
    if not keys(a) or sorted(keys(a))!=sorted(keys(b)) or len(keys(a))!=len(set(keys(a))):reasons.append('mismatch:cases')
    if a.get('coordinator_mode')!='classic' or b.get('coordinator_mode') not in {'graph-reconsider','graph-observe'}:reasons.append('unexpected_modes')
    def summary(r):
        turns=[t for c in r.get('cases',[]) for t in c.get('turns',[])]
        elapsed=[t['elapsed_ms'] for t in turns if 'elapsed_ms' in t]
        passed=lambda c:all(x['status']=='PASS' for x in c.get('checks',[])) and all(x['status']=='PASS' for t in c.get('turns',[]) for x in t.get('checks',[])) and bool(c.get('turns'))
        return {'mode':r.get('coordinator_mode'),'status':r.get('status'),'cases_passed':sum(passed(c) for c in r.get('cases',[])),
            'cases':len(r.get('cases',[])),'bookings':sum(len(c.get('meetings',[])) for c in r.get('cases',[])),
            'provider_calls':r.get('provider_calls'),'cost_usd':r.get('provider_usage',{}).get('cost_usd'),
            'cost_complete':r.get('cost_reporting_complete',False),'mean_turn_ms':round(statistics.mean(elapsed),1) if elapsed else None,
            'median_turn_ms':statistics.median(elapsed) if elapsed else None,
            'reconsiderations':sum((t.get('coordinator_graph') or {}).get('reconsiderations',0) for t in turns),
            'accepted_reconsiderations':sum(bool((t.get('bounded_reconsideration') or {}).get('accepted')) for t in turns),
            'observation_decisions':sum(len((t.get('observation_loop') or {}).get('decisions',[])) for t in turns),
            'observation_rounds':sum((t.get('observation_loop') or {}).get('rounds',0) for t in turns),
            'observation_turns_incomplete':sum((t.get('observation_loop') or {}).get('status') in {'FAIL','PARTIAL','CLARIFICATION_REQUIRED'} for t in turns)}
    sa,sb=summary(a),summary(b)
    complete=all(c.get('turns') and not c.get('instrumentation_error') for r in (a,b) for c in r.get('cases',[]))
    costs=[s['cost_usd'] for s in (sa,sb)]
    return {'status':'NOT_COMPARABLE' if reasons else 'COMPARABLE' if complete else 'INCOMPLETE_EVIDENCE','reasons':reasons,'decision':'REVIEW_REQUIRED',
        'evidence_complete':complete,'catalog_comparison':{'ignored_fields':['projects[].properties[].resources[].asset_id'],'equal_after_identity_projection':catalog(ca)==catalog(cb)},'overall_dialogue_quality':'NOT_EVALUATED','commit':a.get('commit'),'reference':sa,'candidate':sb,
        'total_cost_complete':all(s['cost_complete'] for s in (sa,sb)),
        'total_cost_usd':round(sum(costs),8) if all(isinstance(c,(int,float)) for c in costs) and all(s['cost_complete'] for s in (sa,sb)) else None,
        'limitations':['One pair of short scripted cases is not a statistical estimate.','Pre-plan reconsiderations and post-tool observation decisions are distinct; inspect actual traces.','Provider delivery, Calendar and concurrent PostgreSQL bookings are not evaluated.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.resolve() in {args.reference.resolve(),args.candidate.resolve()}:p.error('Keep source evidence unchanged.')
    result=compare(args.reference,args.candidate);args.output.parent.mkdir(parents=True,exist_ok=True)
    lines=['# Comparación de referencia y candidato','',f"Estado de comparabilidad: {result['status']}. Decisión: revisión humana pendiente.",'','| Modo | Casos sin fallos | Citas | Llamadas | Total USD | Reconsideraciones |','|---|---:|---:|---:|---:|---:|']
    for key in ('reference','candidate'):
        s=result[key];amount=(f"{s['cost_usd']:.8f}" if isinstance(s['cost_usd'],(int,float)) else 'No informado')+(' (parcial)' if not s['cost_complete'] else '');lines.append(f"| {s['mode']} | {s['cases_passed']}/{s['cases']} | {s['bookings']} | {s['provider_calls']} | {amount} | {s['reconsiderations']} |")
    total_label=f"USD {result['total_cost_usd']:.8f}" if result['total_cost_usd'] is not None else 'no calculable con evidencia incompleta'
    lines+=['',f"Total consumido entre ambas: {total_label}.",'','No certifica calidad integral ni autoriza activar el candidato en producción.']
    with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(args.reference,'reference.zip');z.write(args.candidate,'candidate.zip')
        z.writestr('comparison.json',json.dumps(result,indent=2,ensure_ascii=False)+'\n');z.writestr('comparison.md','\n'.join(lines))
    print(json.dumps(result,indent=2));print('Bundle:',str(args.output))
    return 0 if result['status']=='COMPARABLE' else 2

if __name__=='__main__':raise SystemExit(main())
