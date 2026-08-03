from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
import uuid

from app.core.config import settings

SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")

@dataclass(frozen=True)
class StoredCompanyFile:
    relative_path: str
    stored_filename: str

def _root() -> Path:
    root = Path(settings.PROJECT_UPLOAD_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    return root

def _uuid(value: str) -> str:
    try: return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc: raise ValueError("Invalid storage identifier.") from exc

def store_company_file(*, company_id: str, source_id: str, original_filename: str, content: bytes) -> StoredCompanyFile:
    directory = _root() / "companies" / _uuid(company_id) / "company-onboarding" / "sources" / _uuid(source_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    suffix = Path(original_filename).suffix.lower()
    filename = f"original{suffix if SAFE_EXTENSION.fullmatch(suffix) else ''}"
    destination = directory / filename
    descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content); temporary.flush(); os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o640); os.replace(temporary_name, destination)
    except Exception:
        try: os.unlink(temporary_name)
        except FileNotFoundError: pass
        raise
    return StoredCompanyFile(destination.relative_to(_root()).as_posix(), filename)

def resolve_company_file(relative_path: str) -> Path:
    root = _root(); candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents: raise ValueError("Invalid stored file path.")
    return candidate
