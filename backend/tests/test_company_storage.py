from pathlib import Path
import uuid

from app.modules.company_onboarding import storage_service


def test_company_material_is_encrypted_and_integrity_checked(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))
    stored = storage_service.store_company_file(
        company_id=str(uuid.uuid4()), source_id=str(uuid.uuid4()),
        original_filename="company.pdf", content=b"company-confidential-material",
    )
    raw = storage_service.resolve_company_file(stored.relative_path).read_bytes()
    assert raw != b"company-confidential-material"
    assert stored.content_hash
    assert stored.encryption_key_id
    assert storage_service.read_company_file(stored.relative_path, encrypted=True) == b"company-confidential-material"


def test_legacy_company_material_backfill_is_idempotent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))
    relative = f"companies/{uuid.uuid4()}/company-onboarding/sources/{uuid.uuid4()}/legacy.txt"
    path = storage_service._root() / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"legacy-material")

    first = storage_service.encrypt_legacy_company_file(relative)
    once = path.read_bytes()
    second = storage_service.encrypt_legacy_company_file(relative)

    assert first == second
    assert path.read_bytes() == once
    assert storage_service.read_company_file(relative, encrypted=True) == b"legacy-material"
