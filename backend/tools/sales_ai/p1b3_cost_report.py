"""Safe aggregate cost/quality metrics from synthetic-sales-results.zip bundles.

No raw user turns or report contents are printed. The script does not connect
OpenRouter, PostgreSQL or WhatsApp. Run with any number of completed bundles.
"""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def summarize(path):
    path = Path(path)
    with ZipFile(path) as z:
        report = json.loads(z.read('report.json'))
    cases = report.get('cases') or []
    turns = [t for c in cases for t in c.get('turns', [])]
    def observation(turn):
        return (turn.get('observation_loop') or
                ((turn.get('input_trace') or {}).get('observation_loop') or {}))
    def composition(turn):
        metadata = turn.get('metadata') or (turn.get('output') or {}).get('metadata') or {}
        return (metadata.get('composition') or {}).get('context_projection')
    savings = sum(observation(t).get('read_budget', {}).get('saved_decision_calls', 0)
                  for t in turns)
    projection = [composition(t) for t in turns]
    projection = [x for x in projection if isinstance(x, dict)]
    usage = report.get('provider_usage') or {}
    return {
        'commit': report.get('commit'), 'suite': report.get('version'),
        'model': report.get('sales_model'), 'configuration_sha256': report.get('configuration_sha256'),
        'status': report.get('status'), 'scenario_count': report.get('scenario_count'),
        'turn_count': len(turns), 'checks': report.get('summary'),
        'provider_calls': report.get('provider_calls'),
        'prompt_tokens': usage.get('prompt_tokens'),
        'completion_tokens': usage.get('completion_tokens'),
        'cost_usd': usage.get('cost_usd'),
        'responses_with_cost': usage.get('responses_with_cost'),
        'observation_decisions_saved': savings,
        'composition_context_projected_turns': sum(x.get('mode') == 'projected' for x in projection),
        'composition_prompt_bytes_saved': sum(x.get('saved_bytes', 0) for x in projection),
        'composition_prompt_bytes_before': sum(x.get('before_bytes', 0) for x in projection),
        'composition_prompt_bytes_after': sum(x.get('after_bytes', 0) for x in projection),
        'quality_scope': 'automated_checks_not_integral_dialogue_assessment',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', nargs='+', help='Synthetic sales ZIP files')
    args = parser.parse_args()
    rows = [summarize(path) for path in args.bundles]
    print(json.dumps({'version': 'sales-p1b3-cost-report/1.0', 'runs': rows}, indent=2))


if __name__ == '__main__':
    main()
