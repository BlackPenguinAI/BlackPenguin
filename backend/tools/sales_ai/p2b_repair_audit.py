"""P2-B: offline, privacy-conscious repair usage + functional-gate inventory.

Reads completed *synthetic* ZIP bundles. No extraction, network, model requests,
DB connections or behavioral changes. Reports only aggregate/safe allowlisted
fields; never copies raw response, user messages, prompt or repair evidence.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from zipfile import ZipFile, BadZipFile

VERSION = 'sales-p2b-repair-audit/1.0'
MAX_REPORT_BYTES = 64 * 1024 * 1024

# Mapped to exact source actions; anything unrecognized is counted without
# copying untrusted labels or strings into the summary.
STAGES = {
    'declining_a_visit_is_not_cancellation': 'interpretation_consistency.normalize',
    'omit_human_contact_misread_as_visit': 'mixed_human_visit.omit_spurious_visit',
    'reject_unrequested_comparison': 'booking_intent.canonicalize_new_visit',
    'derive_appointment_from_current_visit': 'booking_intent.canonicalize_new_visit',
    'discard_unquoted_historical_selection': 'booking_intent.canonicalize_new_visit',
    'preserve_independently_validated_current_declaration': 'current_declarations.merge',
    'omit_historical_declaration': 'interpretation_input.compile_input',
    'omit_verified_historical_optional_preference': 'interpretation_input.compile_input',
    'omit_verified_historical_request': 'interpretation_input.compile_input',
    'literal_material_read_not_comparison': 'interpretation_wire_repairs.literal_material',
    'literal_visit_not_comparison': 'interpretation_wire_repairs.literal_visit',
    'new_visit_placeholder_is_named_property': 'interpretation_consistency.normalize',
    'named_property_is_selection_not_comparison': 'interpretation_consistency.normalize',
    'explicit_preference_changes_active_subject': 'interpretation_consistency.normalize',
    'bind_anaphoric_material_to_explicit_current_choice': 'interpretation_consistency.normalize',
    'select_exact_backend_public_option': 'interpretation_consistency.normalize',
    'property_information_is_not_visit_consent': 'interpretation_consistency.normalize',
    'preserve_literal_single_material_request': 'interpretation_consistency.normalize',
    'bind_material_owner_from_exact_current_property': 'interpretation_consistency.normalize',
    'preserve_explicit_material_subject': 'interpretation_consistency.normalize',
    'omit_comparison_invented_from_pure_visit': 'interpretation_consistency.normalize',
    'new_visit_is_not_existing_appointment_query': 'interpretation_consistency.normalize',
    'preserve_explicit_new_visit_request': 'interpretation_consistency.normalize',
    'preserve_explicit_new_visit_directive': 'interpretation_consistency.normalize',
    'omit_date_phrase_from_flexible_clock': 'interpretation_consistency.normalize',
    'any_time_is_not_a_clock_range': 'interpretation_consistency.normalize',
    'single_price_question_not_comparison': 'mixed_human_pricing.normalize_misread_price_comparison',
}
PROTECTED_STAGES = frozenset({
    'interpretation_consistency.normalize',
    'mixed_human_visit.omit_spurious_visit',
    'booking_intent.canonicalize_new_visit',
    'current_declarations.merge',
    'interpretation_input.compile_input',
})


def read_report(bundle):
    path = Path(bundle)
    try:
        with ZipFile(path) as z:
            entry = z.getinfo('report.json')
            if entry.file_size > MAX_REPORT_BYTES:
                raise ValueError('Synthetic report exceeds bounded read size.')
            with z.open(entry) as f:
                document = f.read(MAX_REPORT_BYTES + 1)
        if len(document) > MAX_REPORT_BYTES:
            raise ValueError('Synthetic report exceeds bounded read size.')
        report = json.loads(document)
    except (KeyError, BadZipFile, json.JSONDecodeError, OSError) as exc:
        raise ValueError('Input is not a completed synthetic-sales-results.zip.') from exc
    if not isinstance(report, dict) or not isinstance(report.get('cases'), list) or report.get('synthetic_only') is not True:
        raise ValueError('Only synthetic, completed sales reports may be audited.')
    return report


def run_metrics(report, *, label):
    action_counts = Counter()
    stage_counts = Counter()
    attempts = retries = turns = truncations = internal_failures = 0
    financing_queries = financing_reads = visit_queries = visit_reads = 0
    closing_cases = {
        'decline_visit_questions', 'human_then_question', 'human_insists',
        'human_record_then_question', 'human_withdrawal', 'farewell_then_reopen',
        'unavailable_then_close', 'mixed_human_price',
    }
    seen_cases = set()
    for case in report['cases']:
        if not isinstance(case, dict):
            raise ValueError('Invalid synthetic case.')
        seen_cases.add(case.get('case'))
        for turn in case.get('turns', []):
            turns += 1
            journal = turn.get('interpretation_attempts') or []
            if not isinstance(journal, list):
                raise ValueError('Invalid interpretation journal.')
            attempts += len(journal)
            retries += max(0, len(journal)-1)
            for item in journal:
                if item.get('raw_response_truncated'):
                    truncations += 1
                for note in item.get('normalizations') or []:
                    action = (note.get('action') if isinstance(note, dict) else None)
                    action = action if action in STAGES else 'unrecognized_action'
                    action_counts[action] += 1
                    stage_counts[STAGES.get(action, 'unmapped')] += 1
            trace = (turn.get('input_trace') or {}).get('observation_loop') or {}
            if trace.get('status') == 'FAIL':
                internal_failures += 1
            # These are the *current synthetic fixture* predicates. They do not
            # authorize model behavior and never appear verbatim in the output.
            message = turn.get('lead_message') or ''
            u = turn.get('understanding') or {}
            if isinstance(message,str) and 'What financing options do you offer?' in message:
                financing_queries += 1
                if (trace.get('status') == 'PASS' and not u.get('requires_clarification')
                    and not trace.get('unread_required_tasks')
                    and any((tool.get('arguments') or {}).get('topic')=='financing'
                            and tool.get('status')=='success' for tool in trace.get('tools',[]))):
                    financing_reads += 1
            if case.get('case')=='unavailable_then_close' and turn.get('turn')==1:
                visit_queries += 1
                meta=(turn.get('output') or {}).get('metadata') or {}
                if (trace.get('status')=='PASS' and not meta.get('reference_question')
                    and any(v.get('operation_id')=='visit_availability' for v in trace.get('observations',[]))):
                    visit_reads += 1
    usage = report.get('provider_usage') or {}
    checks = report.get('summary') or {}
    def count(value):
        return value if type(value) is int and value >= 0 else None
    def amount(value):
        return value if type(value) in (int,float) and value >= 0 else None
    closing = seen_cases == closing_cases
    gate = ('PASS_FOCUSED' if financing_queries==financing_reads==4
            and visit_queries==visit_reads==1 and internal_failures==0
            and checks.get('FAIL',0)==0 else 'BLOCKED_FOCUSED') if closing else 'NOT_EVALUATED'
    result = {
        'label': label,
        'commit': str(report.get('commit') or '')[:40],
        'configuration_sha256': str(report.get('configuration_sha256') or '')[:64],
        'model': str(report.get('sales_model') or '')[:120],
        'scenarios': count(report.get('scenario_count')),
        'turns': turns,
        'checks': {key:count(checks.get(key)) for key in ('PASS','FAIL','BLOCKED')},
        'provider_calls':count(report.get('provider_calls')),
        'prompt_tokens':count(usage.get('prompt_tokens')),
        'completion_tokens':count(usage.get('completion_tokens')),
        'cost_usd':amount(usage.get('cost_usd')),
        'interpretation_attempts':attempts,
        'interpretation_retries':retries,
        'truncated_raw_packets':truncations,
        'internal_observation_failures':internal_failures,
        'financing_queries':financing_queries,
        'financing_reads_verified':financing_reads,
        'visit_queries':visit_queries,
        'visit_availability_verified':visit_reads,
        'focused_functional_gate':gate,
        'repair_actions':dict(sorted(action_counts.items())),
        'repair_stages':dict(sorted(stage_counts.items())),
    }
    return result


def audit(paths):
    if not paths:
        raise ValueError('Provide at least one completed synthetic ZIP.')
    runs = [run_metrics(read_report(path), label=f'run_{i}') for i,path in enumerate(paths, 1)]
    actions = Counter()
    stages = Counter()
    for run in runs:
        actions.update(run['repair_actions'])
        stages.update(run['repair_stages'])
    return {
        'version':VERSION,
        'source':'synthetic_traces_only',
        'run_count':len(runs),
        'turn_count':sum(run['turns'] for run in runs),
        'interpretation_attempts':sum(run['interpretation_attempts'] for run in runs),
        'interpretation_retries':sum(run['interpretation_retries'] for run in runs),
        'repair_actions':dict(sorted(actions.items())),
        'repair_stages':dict(sorted(stages.items())),
        'focused_gate_blocked_runs':sum(r['focused_functional_gate']=='BLOCKED_FOCUSED' for r in runs),
        'active_protected_stages': sorted(set(stages)&PROTECTED_STAGES),
        'decision':'NO_AUTOMATIC_REMOVAL',
        'reason':'A zero trigger count never demonstrates that a repair is redundant. Current synthetic runs share scenarios and lack complete provider-context replay.',
        'privacy':'No raw lead text, model responses, evidence quotations or credentials in this report.',
        'runs':runs,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles',required=True,nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    if args.output.resolve() in {p.resolve() for p in args.bundles}:
        parser.error('Refusing to overwrite an input evidence bundle.')
    result=audit(args.bundles)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'version':VERSION,'run_count':result['run_count'],
                      'turn_count':result['turn_count'],'repair_stages':result['repair_stages'],
                      'decision':result['decision']},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
