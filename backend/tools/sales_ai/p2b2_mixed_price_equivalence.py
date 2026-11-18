"""P2-B.2: offline counterfactuals for the mixed-human single-price repair.

Synthetic requests only. Model, network, production database and external effects
are never invoked. The repair remains enabled in production. The optional
archived replay is processed only in memory and reports aggregate counters.
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from unittest.mock import patch

from app.modules.sales_agent.interpretation_input import (
    Input, ProviderInput, PROVIDER_VERSION, VERSION, compile_input,
)
from .p1c_interpretation_selftest import packet, information, target
from .p2b_repair_ablation import decode_samples, noop

VERSION_REPORT = 'sales-p2b2-mixed-price-equivalence/1.0'
REPAIR = 'app.modules.sales_agent.mixed_human_pricing.normalize_misread_price_comparison'
REPAIR_ACTION = 'single_price_question_not_comparison'
PRICE_MESSAGE = 'I want to speak to a human. What is the price of Bay Residence?'
PRICE_QUESTION = 'What is the price of Bay Residence?'


@dataclass(frozen=True)
class Case:
    code: str
    text: str
    question: str
    kind: str = 'comparison'  # model emits one-member comparison, or pricing
    schema_version: str = 'v3'
    property_name: str = 'Bay Residence'
    approved_names: tuple = ('Bay Residence',)
    should_repair: bool = False
    members: tuple = ()
    extra_human: bool = False
    selection: bool = False
    clarification: bool = False


CASES = (
    Case('v3_one_property_price_misread', PRICE_MESSAGE, PRICE_QUESTION, should_repair=True),
    Case('v2_archived_one_property_price_misread', PRICE_MESSAGE, PRICE_QUESTION,
         schema_version='v2', should_repair=True),
    Case('v3_cost_question_misread', 'I want to speak to a human. How much does Bay Residence cost?',
         'How much does Bay Residence cost?', should_repair=True),
    Case('v3_casefold_name_misread', 'I want to speak to a human. What is the price of bay residence?',
         'What is the price of bay residence?', property_name='bay residence', should_repair=True),
    Case('v3_direct_price_already_correct', PRICE_MESSAGE, PRICE_QUESTION,kind='pricing'),
    Case('v3_real_two_property_comparison', 'Compare Cedar Loft and Cedar Studio by price.',
         'Compare Cedar Loft and Cedar Studio by price.', members=('Cedar Loft','Cedar Studio'),
         approved_names=('Cedar Loft','Cedar Studio')),
    Case('v3_unapproved_property', PRICE_MESSAGE, PRICE_QUESTION, approved_names=()),
    Case('v3_ambiguous_approved_property', PRICE_MESSAGE, PRICE_QUESTION,
         approved_names=('Bay Residence','Bay Residence')),
    Case('v3_other_catalog_only', PRICE_MESSAGE, PRICE_QUESTION,
         approved_names=('Cedar Studio',)),
    Case('v3_third_party_report', 'My friend said: '+PRICE_MESSAGE, PRICE_QUESTION),
    Case('v3_hypothetical_human', 'If I want to speak to a human. '+PRICE_QUESTION,PRICE_QUESTION),
    Case('v3_quoted_text', '"'+PRICE_MESSAGE+'"',PRICE_QUESTION),
    Case('v3_additional_visit_instruction', PRICE_MESSAGE+' Please book a visit.', PRICE_QUESTION),
    Case('v3_additional_material_instruction', PRICE_MESSAGE+' Send photos too.', PRICE_QUESTION),
    Case('v3_separately_extracted_human_request',PRICE_MESSAGE,PRICE_QUESTION,extra_human=True),
    Case('v3_explicit_selection_guard',PRICE_MESSAGE,PRICE_QUESTION,selection=True),
    Case('v3_existing_clarification_guard',PRICE_MESSAGE,PRICE_QUESTION,clarification=True),
    Case('v3_nonhuman_price_question',PRICE_QUESTION,PRICE_QUESTION),
)


def input_document(case):
    """Use production schema validation, not hand-constructed internal IDs."""
    members=case.members or (case.property_name,)
    comparison=dict(topic='comparison', polarity='request', evidence=case.question,
                    members=[target(name) for name in members], criteria=['price'],
                    include_current=False, include_all=False, all_kind='property',
                    operation='compare', feature=None)
    if case.kind=='pricing':
        requests=[dict(topic='pricing',polarity='request',subject=None,
                       evidence=case.question,target=target(case.property_name))]
        comparison=None
    else:
        requests=[]
    if case.extra_human:
        requests.append(information('human','I want to speak to a human.'))
    row=packet(text=case.text,requests=requests,comparison=comparison,
               selection=target(case.property_name) if case.selection else None)
    row['confidence']=0.0
    if case.clarification:
        row['requires_clarification']=True
        row['clarification_question']='Which property would you like to discuss?'
    if case.schema_version=='v2':
        comparison=row.pop('comparison')
        row['requests'].append(comparison)
        row['version']=VERSION
        row=Input.model_validate(row).model_dump(mode='json')
    else:
        row=ProviderInput.model_validate(row).model_dump(mode='json')
    return json.dumps(row,ensure_ascii=False)


def evaluate_case(case):
    raw=input_document(case)
    opts={'approved_names':case.approved_names}
    baseline,notes=compile_input(raw,case.text,**opts)
    baseline.check_evidence(case.text)
    with patch(REPAIR,side_effect=noop):
        counterfactual,_=compile_input(raw,case.text,**opts)
    counterfactual.check_evidence(case.text)
    changed=baseline.model_dump(mode='json')!=counterfactual.model_dump(mode='json')
    fired=any(n.get('action')==REPAIR_ACTION for n in notes)
    if changed!=case.should_repair or fired!=case.should_repair:
        raise AssertionError('Counterfactual discrepancy in '+case.code)
    if baseline.confidence!=counterfactual.confidence or baseline.confidence!=0.0:
        raise AssertionError('Model confidence was changed in '+case.code)
    # The normalizer never produces a write instruction or external effect.
    for contract in (baseline,counterfactual):
        if any(getattr(contract,field) is not None for field in
               ('visit','reschedule','cancellation','wait')):
            raise AssertionError('Unexpected action consent in '+case.code)
        if contract.permits('appointment') or contract.permits('opt_out'):
            raise AssertionError('Unexpected action permission in '+case.code)
    if case.should_repair:
        if (baseline.comparison is not None or counterfactual.comparison is None or
            not baseline.permits('pricing') or counterfactual.permits('pricing') or
            len(baseline.requests)!=1 or len(baseline.references)!=1 or
            baseline.requests[0].evidence!=case.question or
            baseline.references[0].kind!='property' or
            baseline.references[0].evidence!=case.property_name):
            raise AssertionError('Price-read semantics were not restored in '+case.code)
        # Compare repaired wrong provider packet to correctly classified v3 packet.
        direct=Case(code='correct',text=case.text,question=case.question,kind='pricing',
                    property_name=case.property_name,approved_names=case.approved_names)
        correct,_=compile_input(input_document(direct),case.text,**opts)
        correct.check_evidence(case.text)
        if correct.model_dump(mode='json')!=baseline.model_dump(mode='json'):
            raise AssertionError('Repaired packet differs from correct price reading in '+case.code)
    elif case.kind=='pricing':
        if baseline.comparison is not None or not baseline.permits('pricing'):
            raise AssertionError('Correctly classified pricing question was lost.')
    elif case.members:
        if baseline.comparison is None or len(baseline.comparison.reference_ids)!=2:
            raise AssertionError('Genuine comparison was lost.')
    return {'code':case.code,'required':case.should_repair,
            'changed':changed,'normalizer_triggered':fired,'validated':True}


def recorded_replay(paths, *, max_packets=200, approved_names=('Bay Residence',)):
    """Recheck prior *accepted* synthetic provider responses, with no side effects."""
    if not paths:
        return {'bundles':0,'unique_packets':0,'replayable':0,'different':0,
                'rejected':0,'skipped':{},'insufficient_for_removal':True}
    samples,skipped=decode_samples(paths,max_packets=max_packets)
    different=replayable=rejected=0
    for raw,text,history,previous_reply,metadata in samples:
        opts=dict(historical_messages=history,previous_reply=previous_reply,
                  previous_metadata=metadata,approved_names=approved_names)
        try:
            before,_=compile_input(raw,text,**opts)
            before.check_evidence(text)
            with patch(REPAIR,side_effect=noop):
                after,_=compile_input(raw,text,**opts)
            after.check_evidence(text)
            replayable+=1
            different+=before.model_dump(mode='json')!=after.model_dump(mode='json')
        except Exception:
            rejected+=1
    return {'bundles':len(paths),'unique_packets':len(samples),'replayable':replayable,
            'different':different,'rejected':rejected,'skipped':skipped,
            'insufficient_for_removal':True}


def report(*, bundles=(), approved_names=('Bay Residence',)):
    rows=[evaluate_case(c) for c in CASES]
    replay=recorded_replay(bundles,approved_names=approved_names)
    positives=sum(c['changed'] for c in rows)
    if positives<3 or any(c['changed']!=c['required'] for c in rows):
        raise AssertionError('Targeted tests did not demonstrate necessary repair.')
    return {'version':VERSION_REPORT,'scope':'synthetic_compiler_counterfactuals_and_optional_accepted_packet_replay',
            'production_code_changed':False,'network_calls':0,'model_calls':0,
            'synthetic_cases':len(rows),'targeted_misreads_repaired':positives,
            'safe_guard_cases':len(rows)-positives,'counterfactual_differences':positives,
            'recorded_replay':replay,
            'decision':'KEEP_REPAIR', 'safe_to_remove':False,
            'reason':'An admissible v3 one-member comparison still needs the repair to preserve a grounded pricing read.',
            'limitations':'Finite synthetic cases and partial historical context. Planner tests run separately under pytest with isolated SQLite.',
            'privacy':'Only predefined test IDs and aggregate counters are emitted; no raw message or model response.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--bundles',nargs='*',default=[],type=Path)
    p.add_argument('--approved-name',action='append',default=[],help='Approved synthetic property label')
    args=p.parse_args(argv)
    if args.output.resolve() in {path.resolve() for path in args.bundles}:
        p.error('The result must never overwrite an input ZIP.')
    names=tuple(args.approved_name) if args.approved_name else ('Bay Residence',)
    result=report(bundles=args.bundles,approved_names=names)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('decision','synthetic_cases','targeted_misreads_repaired',
                                           'safe_guard_cases','recorded_replay','safe_to_remove')},indent=2))
    return 0 if result['decision']=='KEEP_REPAIR' else 2


if __name__=='__main__':raise SystemExit(main())
