"""Private-data-free P1-C.1 commercial checks from a local synthetic ZIP.

Never calls the provider or any database. Outputs aggregate metrics only.
"""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile

VERSION='sales-p1c1-audit/1.0'


def evaluate(path):
    with ZipFile(path) as z:
        report=json.loads(z.read('report.json'))
    failures=[]
    financing=[]
    visits=[]
    internal=[]
    for case in report.get('cases',[]):
        for t in case.get('turns',[]):
            statement=t.get('lead_message','')
            obs=((t.get('input_trace') or {}).get('observation_loop') or {})
            u=t.get('understanding') or {}
            if obs.get('status')=='FAIL':
                internal.append({'case':case['case'],'turn':t['turn'],'status':'FAIL'})
            if 'What financing options do you offer?' in statement:
                read=any(x.get('arguments',{}).get('topic')=='financing'
                         and x.get('status')=='success' for x in obs.get('tools',[]))
                ok=not u.get('requires_clarification') and obs.get('status')=='PASS' and read and not obs.get('unread_required_tasks')
                financing.append({'case':case['case'],'turn':t['turn'],'status':'PASS' if ok else 'FAIL'})
            if case.get('case')=='unavailable_then_close' and t.get('turn')==1:
                avail=any(o.get('operation_id')=='visit_availability'
                    for o in obs.get('observations',[]))
                ok=obs.get('status')=='PASS' and avail and not (t.get('output') or {}).get('metadata',{}).get('reference_question')
                visits.append({'case':case['case'],'turn':t['turn'],'status':'PASS' if ok else 'FAIL'})
    if len(financing)!=4:failures.append('expected_four_financing_questions')
    if len(visits)!=1:failures.append('expected_one_scoped_visit')
    if any(x['status']=='FAIL' for x in [*financing,*visits,*internal]):
        failures.append('unfulfilled_required_observation_or_clarification')
    summary=report.get('summary') or {}
    if report.get('scenario_count')!=8 or summary.get('FAIL',0):
        failures.append('focused_closing_check_regression')
    usage=report.get('provider_usage') or {}
    turns=[t for c in report.get('cases',[]) for t in c.get('turns',[])]
    return {'version':VERSION,'commit':report.get('commit'),
        'scenarios':report.get('scenario_count'),'turns':len(turns),
        'checks':summary,'provider_calls':report.get('provider_calls'),
        'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),
        'cost_usd':usage.get('cost_usd'),
        'interpretation_retries':sum(max(0,len(t.get('interpretation_attempts') or [])-1) for t in turns),
        'finance_queries':len(financing),'finance_observed':sum(x['status']=='PASS' for x in financing),
        'scoped_visits':len(visits),'scoped_visits_observed':sum(x['status']=='PASS' for x in visits),
        'internal_observation_failures':len(internal),
        'failures':failures,'decision':'PASS_FOCUSED_GATE' if not failures else 'BLOCKED',
        'limitations':'Synthetic scripted coverage, not production PostgreSQL, Calendar or WhatsApp.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.candidate.resolve()==args.output.resolve():parser.error('Never overwrite the evidence ZIP')
    value=evaluate(args.candidate)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps({k:value[k] for k in ('decision','checks','provider_calls','interpretation_retries','finance_observed','scoped_visits_observed','failures')},indent=2))
    return 0 if value['decision']=='PASS_FOCUSED_GATE' else 2


if __name__=='__main__':raise SystemExit(main())
