"""Offline contract replay only; never accesses DB, keys, models or messaging."""
import argparse
import hashlib
import json
from pathlib import Path
from .understanding_contract import parse, response_schema
from .understanding_prompt import PROMPT_VERSION, SYSTEM_PROMPT


def evaluate(case):
    value = parse(json.dumps(case['model_output']), case['inbound'])
    expected = case['expected']
    failures = []
    for topic, subject in expected.get('allowed', []):
        if not value.permits(topic, subject):
            failures.append(f'Expected allowed: {topic}/{subject}')
    for topic, subject in expected.get('blocked', []):
        if value.permits(topic, subject):
            failures.append(f'Expected blocked: {topic}/{subject}')
    if len(value.alternatives) != expected['alternative_count'] or value.requires_clarification != expected['clarification']:
        failures.append('Unexpected relations or clarification')
    return {'id': case['id'], 'passed': not failures, 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.cases.read_bytes()
    fixture = json.loads(raw)
    if fixture.get('version') != 'sales-understanding-fixtures/1.0' or fixture.get('mode') != 'scripted-contract-not-model-quality':
        parser.error('Unsupported fixture version/mode; this command evaluates scripted contracts only.')
    cases = fixture['cases']
    if not cases or len({c['id'] for c in cases}) != len(cases):
        parser.error('Fixture IDs must be unique and the cases cannot be empty.')
    results = []
    for case in cases:
        try:
            results.append(evaluate(case))
        except (ValueError, TypeError) as exc:
            results.append({'id': case.get('id'), 'passed': False, 'failures': [type(exc).__name__]})
    report = {'version': 'sales-understanding-evaluation/1.0', 'mode': 'offline-scripted-contract',
        'model_quality_evaluated': False, 'external_actions': 0, 'prompt_version': PROMPT_VERSION,
        'model': None, 'prompt_sha256': hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        'cases_sha256': hashlib.sha256(raw).hexdigest(),
        'schema_sha256': hashlib.sha256(json.dumps(response_schema(), sort_keys=True).encode()).hexdigest(),
        'total': len(results), 'passed': sum(r['passed'] for r in results), 'results': results}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(f"offline_contract: {report['passed']}/{report['total']}; model_quality_evaluated=false; external_actions=0")
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
