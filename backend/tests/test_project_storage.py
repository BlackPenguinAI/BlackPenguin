from pathlib import Path
import uuid

import pytest

from app.modules.projects import storage_service


def test_project_file_is_stored_under_company_project_and_source(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))
    company_id, project_id, source_id = (str(uuid.uuid4()) for _ in range(3))

    stored = storage_service.store_project_file(
        company_id=company_id,
        project_id=project_id,
        source_id=source_id,
        original_filename="brochure.pdf",
        content=b"%PDF-test",
    )

    assert stored.relative_path == (
        f"companies/{company_id}/projects/{project_id}/sources/{source_id}/original.pdf"
    )
    assert storage_service.resolve_project_file(stored.relative_path).read_bytes() == b"%PDF-test"


def test_storage_rejects_path_traversal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))

    with pytest.raises(ValueError):
        storage_service.resolve_project_file("../../etc/passwd")


def test_project_directory_can_be_quarantined_and_restored(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))
    company_id, project_id, source_id = (str(uuid.uuid4()) for _ in range(3))
    stored = storage_service.store_project_file(
        company_id=company_id,
        project_id=project_id,
        source_id=source_id,
        original_filename="inventory.xlsx",
        content=b"PK-test",
    )

    move = storage_service.quarantine_project_files(company_id, project_id)
    assert move is not None
    assert not storage_service.resolve_project_file(stored.relative_path).exists()

    storage_service.restore_quarantined_files(move)
    assert storage_service.resolve_project_file(stored.relative_path).exists()
