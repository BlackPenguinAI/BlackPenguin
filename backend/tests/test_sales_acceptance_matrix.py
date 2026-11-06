"""Every original PDF issue keeps an explicit, checkable regression reference."""
import json
import os
from pathlib import Path


def test_all_27_requirements_are_present_with_real_regression_paths():
    # Deployment tests run at /app/tests against the immutable backend image.
    # Their documentation/reference tree is mounted separately, read-only.
    configured_root = os.environ.get('SALES_ACCEPTANCE_ROOT')
    root = Path(configured_root) if configured_root is not None else Path(__file__).resolve().parents[2]
    assert root.is_absolute(), 'SALES_ACCEPTANCE_ROOT must be an absolute path.'
    assert root.is_dir(), f'Acceptance reference root is missing: {root}'
    assert (root/'docs/sales-agent-acceptance-matrix.json').is_file(), (
        f'Acceptance matrix is missing under {root}; mount docs and backend/tests read-only in the preflight container.')
    matrix = json.loads((root/'docs/sales-agent-acceptance-matrix.json').read_text())
    assert [r['id'] for r in matrix['issues']] == list(range(1, 28))
    assert matrix['base_commit'] == '83706ec2382627a86b9c331ff781df6649577b66'
    assert matrix['pending_decisions']
    for row in matrix['issues']:
        assert row['priority'] in {'P0','P1'} and row['acceptance'] and row['scope']
        assert row['live_model_e2e'] == 'not_evaluated_in_groups_1_3'
        for relative in row['existing_test_files']:
            assert (root/relative).is_file(), (row['id'], relative)
