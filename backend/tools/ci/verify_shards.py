"""Fail the release gate for missing, inconsistent or unsuccessful shards."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from shard_tests import discover


def verify(tests: Path, evidence: Path, count: int) -> None:
    expected = set(discover(tests))
    plans = []
    for index in range(1, count + 1):
        manifest = json.loads((evidence / f'shard-{index}-manifest.json').read_text())
        if manifest['shard'] != index or manifest['count'] != count:
            raise ValueError('Wrong shard identity.')
        groups = manifest['groups']
        signature = hashlib.sha256(json.dumps(groups, sort_keys=True).encode()).hexdigest()
        if signature != manifest['plan_sha256'] or len(groups) != count:
            raise ValueError('Invalid partition signature.')
        assigned = [name for group in groups for name in group['files']]
        if len(assigned) != len(expected) or len(set(assigned)) != len(assigned) or set(assigned) != expected:
            raise ValueError('Missing or repeated source modules.')
        report = ET.parse(evidence / f'backend-junit-{index}.xml')
        cases = list(report.iter('testcase'))
        if not cases or any(list(report.iter(tag)) for tag in ('failure', 'error')):
            raise ValueError('Missing tests or failed JUnit report.')
        # Every assigned module must appear in the report (all-skipped modules count).
        reported = {c.get('classname', '') for c in cases}
        for filename in groups[index - 1]['files']:
            module = 'tests.' + filename[:-3].replace('/', '.')
            if not any(name == module or name.startswith(module + '.') for name in reported):
                raise ValueError(f'Assigned module absent from JUnit: {filename}')
        plans.append(signature)
    if len(set(plans)) != 1:
        raise ValueError('Shards did not execute the same partition plan.')
    print(f'PASS: {len(expected)} modules covered exactly once by {count} successful shards.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--count', type=int, default=3)
    args = parser.parse_args()
    verify(args.tests, args.evidence, args.count)


if __name__ == '__main__':
    main()
