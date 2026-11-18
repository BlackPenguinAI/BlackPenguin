"""P2-B: offline counterfactual compiler replay; NEVER disables a production repair.

Temporarily replaces one wire-normalizer at a time *inside this test process*,
then compares fully validated Understanding JSON to the unmodified compiler.
No mocks are persisted and no production code/DB or provider is modified.
The replay lacks some exact runtime scope and policy context, so equality only
means 'no difference in this narrow sample', NOT permission to remove code.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from .p2b_repair_audit import read_report

VERSION='sales-p2b-repair-ablation/1.0'
STAGES={
    'contextual_answers.repair':('app.modules.sales_agent.contextual_answers.repair',2),
    'interpretation_wire_repairs.literal_social_or_need':('app.modules.sales_agent.interpretation_wire_repairs.literal_social_or_need',1),
    'interpretation_wire_repairs.literal_material':('app.modules.sales_agent.interpretation_wire_repairs.literal_material',1),
    'interpretation_wire_repairs.literal_visit':('app.modules.sales_agent.interpretation_wire_repairs.literal_visit',1),
    'interpretation_wire_repairs.literal_property_choice':('app.modules.sales_agent.interpretation_wire_repairs.literal_property_choice',1),
    'mixed_human_visit.omit_spurious_visit':('app.modules.sales_agent.mixed_human_visit.omit_spurious_visit',1),
    'mixed_human_pricing.normalize_misread_price_comparison':('app.modules.sales_agent.mixed_human_pricing.normalize_misread_price_comparison',2),
    'booking_intent.canonicalize_new_visit':('app.modules.sales_agent.booking_intent.canonicalize_new_visit',2),
}


def noop(data, *args, **kwargs):
    return data, []


def decode_samples(paths, *, max_packets):
    seen=set()
    samples=[]
    counts=Counter()
    for path in paths:
        report=read_report(path)
        for case in report['cases']:
            prior_messages=[]
            previous_reply=''
            previous_metadata=None
            for turn in case.get('turns',[]):
                lead_text=turn.get('lead_message')
                if not isinstance(lead_text,str):
                    counts['missing_current_message']+=1
                    continue
                for attempt in turn.get('interpretation_attempts') or []:
                    if attempt.get('outcome')!='accepted':
                        counts['nonaccepted_attempt']+=1
                        continue
                    raw=attempt.get('raw_response')
                    if not isinstance(raw,str) or attempt.get('raw_response_truncated'):
                        counts['missing_or_truncated_packet']+=1
                        continue
                    sha=hashlib.sha256(raw.encode('utf-8')).hexdigest()
                    if attempt.get('raw_response_sha256') not in (None,sha):
                        counts['sha256_mismatch']+=1
                        continue
                    key=(sha,lead_text,previous_reply)
                    if key in seen:
                        counts['duplicate_sample']+=1
                        continue
                    seen.add(key)
                    if len(samples)>=max_packets:
                        counts['sample_limit_exceeded']+=1
                        continue
                    samples.append((raw,lead_text,tuple(prior_messages),previous_reply,previous_metadata))
                prior_messages.append(lead_text)
                previous_reply=turn.get('reply') if isinstance(turn.get('reply'),str) else ''
                previous_metadata=(turn.get('output') or {}).get('metadata') or None
    return samples,dict(sorted(counts.items()))


def execute(paths, *, max_packets=300, approved_names=()):
    from app.modules.sales_agent.interpretation_input import compile_input
    if not 1<=max_packets<=10000:
        raise ValueError('Invalid bounded sample limit.')
    samples,skips=decode_samples(paths,max_packets=max_packets)
    # The replay uses provided prior output metadata and historical current text,
    # but not every per-project, per-offer backend capability is present.
    counts={s:Counter() for s in STAGES}
    for raw,text,history,previous_reply,previous_metadata in samples:
        options=dict(historical_messages=history,previous_reply=previous_reply,
            previous_metadata=previous_metadata,approved_names=approved_names)
        try:
            original,_=compile_input(raw,text,**options)
            original.check_evidence(text)
            expected=original.model_dump(mode='json')
        except Exception:
            for counter in counts.values():counter['baseline_not_replayable']+=1
            continue
        for name,(target,_) in STAGES.items():
            counter=counts[name]
            try:
                with patch(target,side_effect=noop):
                    alt,_=compile_input(raw,text,**options)
                    alt.check_evidence(text)
                    actual=alt.model_dump(mode='json')
                counter['equal' if actual==expected else 'different']+=1
            except Exception:
                counter['ablated_rejected']+=1
    result={'version':VERSION,
            'scope':'compile_input_wire_stages_only; missing some authoritative runtime scope',
            'bundles':len(paths),'unique_accepted_packets':len(samples),
            'sampling_skips':skips,
            'stages':{},
            'decision':'NO_AUTOMATIC_REMOVAL',
            'privacy':'Only counters are emitted. No quotations, model replies, prompts, IDs or credentials.',
            'warning':'Zero differences on a finite synthetic replay is NOT proof of redundancy. Do not delete/disable repair functions without full DB, parser, consent and live-context regression coverage.'}
    for name,counts_for_stage in counts.items():
        changes=counts_for_stage['different']+counts_for_stage['ablated_rejected']
        usable=counts_for_stage['different']+counts_for_stage['equal']+counts_for_stage['ablated_rejected']
        result['stages'][name]={
            **{k:counts_for_stage[k] for k in ('equal','different','ablated_rejected','baseline_not_replayable')},
            'replayed_comparisons':usable,
            'classification':'REQUIRED_IN_OBSERVED_SAMPLE' if changes else 'NOT_PROVEN_REDUNDANT',
            'safe_to_remove':False,
        }
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles',nargs='+',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--approved-name',action='append',default=[],help='Verified synthetic property label; repeat for each')
    parser.add_argument('--max-packets',type=int,default=300)
    args=parser.parse_args(argv)
    if args.output.resolve() in {p.resolve() for p in args.bundles}:
        parser.error('Refusing to overwrite input evidence bundle.')
    result=execute(args.bundles,max_packets=args.max_packets,approved_names=args.approved_name)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'version':VERSION,'unique_accepted_packets':result['unique_accepted_packets'],
                      'decision':result['decision'],
                      'stages':{k:v['classification'] for k,v in result['stages'].items()}},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
