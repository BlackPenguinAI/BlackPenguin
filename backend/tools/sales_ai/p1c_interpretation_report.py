"""Privacy-conscious P1-C interpretation baseline/candidate comparison.

Reads only local synthetic ZIP reports or sanitized JSON summaries. Does not
open a connection, call models, print raw messages or modify any database.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from zipfile import ZipFile

VERSION='sales-interpretation-comparison/1.0'


def summarize_bundle(path):
    with ZipFile(path) as archive:
        report=json.loads(archive.read('report.json'))
    cases=report.get('cases',[])
    turns=[row for case in cases for row in case.get('turns',[])]
    attempts=[entry for turn in turns for entry in (turn.get('interpretation_attempts') or [])]
    invalid=[entry for entry in attempts if entry.get('error_code')]
    issues=Counter(i.get('type') or 'unknown' for attempt in invalid
                   for i in (attempt.get('validation_issues') or []))
    usage=report.get('provider_usage') or {}
    return {
        'label':Path(path).stem, 'commit':report.get('commit'),
        'configuration_sha256':report.get('configuration_sha256'),
        'model':report.get('sales_model'),
        'scenarios':sorted(case.get('case') for case in cases),
        'scenario_count':len(cases), 'turn_count':len(turns),
        'checks':report.get('summary') or {},
        'provider_calls':report.get('provider_calls'),
        'prompt_tokens':usage.get('prompt_tokens'),
        'completion_tokens':usage.get('completion_tokens'),
        'cost_usd':usage.get('cost_usd'),
        'responses_with_cost':usage.get('responses_with_cost'),
        'recorded_interpretation_attempts':len(attempts),
        'recorded_interpretation_retries':sum(max(0,len(turn.get('interpretation_attempts') or [])-1)
                                               for turn in turns),
        'invalid_interpretation_attempts':len(invalid),
        'invalid_interpretation_issue_types':dict(sorted(issues.items())),
        'quality_scope':'focused_automated_checks_not_integral_dialogue_evaluation',
    }


def load(path):
    path=Path(path)
    if path.suffix.lower()=='.zip':return summarize_bundle(path)
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('version')=='sales-interpretation-reference/1.0':return result['run']
    if result.get('scenarios') and 'provider_calls' in result:return result
    raise ValueError('Not a compatible ZIP or sanitized interpretation summary.')


def change(reference,candidate,key):
    a=reference.get(key);b=candidate.get(key)
    numeric=isinstance(a,(int,float)) and isinstance(b,(int,float))
    delta=round(b-a,10) if numeric and key=='cost_usd' else (b-a if numeric else None)
    if delta==0:delta=0.0 if key=='cost_usd' else 0
    percent=round(delta/a*100,2) if numeric and a else None
    if percent==0:percent=0.0
    return {'before':a,'after':b,'delta':delta,'percent':percent}


def compare(reference,candidate):
    same_cohort=(reference['scenarios']==candidate['scenarios']
                 and reference['turn_count']==candidate['turn_count'])
    same_configuration=(reference.get('configuration_sha256') == candidate.get('configuration_sha256')
                        and reference.get('model') == candidate.get('model'))
    before=reference.get('checks') or {};after=candidate.get('checks') or {}
    quality_ok=(after.get('FAIL',0)==0 and after.get('BLOCKED',0)<=before.get('BLOCKED',0)
                and after.get('PASS',0)>=before.get('PASS',0))
    return {'version':VERSION, 'reference_commit':reference.get('commit'),
            'candidate_commit':candidate.get('commit'), 'model':candidate.get('model'),
            'same_scenarios_and_turn_count':same_cohort,
            'same_published_configuration':same_configuration,
            'checks':{'reference':before,'candidate':after},
            'no_new_automated_check_regressions':quality_ok if same_cohort else None,
            'metrics':{key:change(reference,candidate,key) for key in (
                'provider_calls','prompt_tokens','completion_tokens','cost_usd',
                'recorded_interpretation_retries','invalid_interpretation_attempts')},
            'reference_issue_types':reference.get('invalid_interpretation_issue_types'),
            'candidate_issue_types':candidate.get('invalid_interpretation_issue_types'),
            'decision':'REVIEW_DIALOGUES_AND_REPEAT' if same_cohort and same_configuration and quality_ok else 'BLOCKED_OR_INCOMPARABLE',
            'caveat':'Provider stochasticity. Fewer retries in one run do not prove causality or statistical significance.',
        }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',required=True,type=Path)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    output=compare(load(args.reference),load(args.candidate))
    if args.output.resolve() in (args.reference.resolve(),args.candidate.resolve()):
        parser.error('The report must not overwrite its source.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:output[k] for k in ('decision','same_scenarios_and_turn_count',
                                           'same_published_configuration','metrics')},indent=2))
    return 0 if output['decision']!='BLOCKED_OR_INCOMPARABLE' else 2


if __name__=='__main__':raise SystemExit(main())
