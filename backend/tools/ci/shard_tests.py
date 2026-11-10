"""Balance complete pytest modules; discover new files on every execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


def discover(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*.py')
                  if (p.name.startswith('test_') or p.name.endswith('_test.py'))
                  and not any(part.startswith('.') or part == '__pycache__'
                              for part in p.relative_to(root).parts))


def partition(files: list[str], weights: dict[str, float], count: int) -> list[dict]:
    if count < 1 or len(files) != len(set(files)) or not files:
        raise ValueError('Provide a positive shard count and unique, non-empty test files.')
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in weights.values()):
        raise ValueError('Historical durations must be finite and nonnegative.')
    groups = [{'files': [], 'estimated_seconds': 0.0} for _ in range(count)]
    # A new module is always included, with a conservative initial weight.
    weight = lambda name: max(float(weights.get(name, 5.0)), 0.001)
    for name in sorted(files, key=lambda name: (-weight(name), name)):
        index = min(range(count), key=lambda i: (groups[i]['estimated_seconds'], i))
        groups[index]['files'].append(name)
        groups[index]['estimated_seconds'] += weight(name)
    assigned = [name for group in groups for name in group['files']]
    if len(assigned) != len(files) or set(assigned) != set(files):
        raise ValueError('The test partition is incomplete or contains duplicates.')
    for group in groups:
        group['files'].sort()
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, default=Path('/app/tests'))
    parser.add_argument('--weights', type=Path,
                        default=Path(__file__).with_name('test_durations.json'))
    parser.add_argument('--shard', type=int, required=True, help='One-based shard index')
    parser.add_argument('--count', type=int, default=3)
    parser.add_argument('--evidence', type=Path, default=Path('/evidence'))
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.shard <= args.count:
        parser.error('Shard must be between 1 and count.')
    files = discover(args.tests)
    weights = json.loads(args.weights.read_text())['durations_seconds']
    groups = partition(files, weights, args.count)
    selected = groups[args.shard - 1]
    if not selected['files']:
        parser.error('Empty shard; reduce the shard count.')
    args.evidence.mkdir(parents=True, exist_ok=True)
    manifest = {'version': 1, 'shard': args.shard, 'count': args.count,
                'discovered_files': len(files), 'groups': groups,
                'plan_sha256': hashlib.sha256(json.dumps(groups, sort_keys=True).encode()).hexdigest()}
    path = args.evidence / f'shard-{args.shard}-manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f"Shard {args.shard}/{args.count}: {len(selected['files'])}/{len(files)} modules; "
          f"historical estimate={selected['estimated_seconds']:.2f}s", flush=True)
    if args.plan_only:
        return 0
    return subprocess.run([sys.executable, '-m', 'pytest', '-q',
                           *(str(args.tests / name) for name in selected['files']),
                           '--durations=30', '--disable-warnings',
                           f'--junitxml={args.evidence / f"backend-junit-{args.shard}.xml"}'],
                          check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
