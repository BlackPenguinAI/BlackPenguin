"""Exercise a flattened /app/tests layout without a full repository beside it."""
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[2]


def isolated_layout(tmp_path, monkeypatch):
    staged = tmp_path/'image/app/tests/test_sales_acceptance_matrix.py'
    staged.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).with_name('test_sales_acceptance_matrix.py'), staged)
    references = tmp_path/'preflight'
    (references/'docs').mkdir(parents=True)
    matrix_path = ROOT/'docs/sales-agent-acceptance-matrix.json'
    # In CI this test itself also uses the explicit reference mount.
    import os
    if os.environ.get('SALES_ACCEPTANCE_ROOT'):
        matrix_path = Path(os.environ['SALES_ACCEPTANCE_ROOT'])/'docs/sales-agent-acceptance-matrix.json'
    shutil.copy2(matrix_path, references/'docs/sales-agent-acceptance-matrix.json')
    matrix = json.loads(matrix_path.read_text())
    for issue in matrix['issues']:
        for relative in issue['existing_test_files']:
            destination = references/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_root = matrix_path.parent.parent
            shutil.copy2(source_root/relative, destination)
    spec = importlib.util.spec_from_file_location('isolated_acceptance', staged)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('SALES_ACCEPTANCE_ROOT', str(references))
    return module, references


def test_flattened_tests_pass_with_separate_reference_mount(tmp_path, monkeypatch):
    module, _ = isolated_layout(tmp_path, monkeypatch)
    module.test_all_27_requirements_are_present_with_real_regression_paths()


def test_original_flattened_layout_failure_is_reproduced(tmp_path, monkeypatch):
    module, _ = isolated_layout(tmp_path, monkeypatch)
    monkeypatch.delenv('SALES_ACCEPTANCE_ROOT')
    with pytest.raises(AssertionError, match='Acceptance matrix is missing'):
        module.test_all_27_requirements_are_present_with_real_regression_paths()


@pytest.mark.parametrize('missing', ['docs/sales-agent-acceptance-matrix.json', 'backend/tests/test_catalog_789.py'])
def test_missing_resources_still_fail_not_skip(tmp_path, monkeypatch, missing):
    module, references = isolated_layout(tmp_path, monkeypatch)
    (references/missing).unlink()
    with pytest.raises(AssertionError):
        module.test_all_27_requirements_are_present_with_real_regression_paths()


def test_relative_override_is_rejected(tmp_path, monkeypatch):
    module, _ = isolated_layout(tmp_path, monkeypatch)
    monkeypatch.setenv('SALES_ACCEPTANCE_ROOT', 'relative')
    with pytest.raises(AssertionError, match='absolute path'):
        module.test_all_27_requirements_are_present_with_real_regression_paths()
