from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import uuid

from app.core.config import settings


@dataclass(frozen=True)
class StoredMeetingFile:
    relative_path: str


def upload_root() -> Path:
    root = Path(settings.PROJECT_UPLOAD_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    return root


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid storage identifier.") from exc


def store_meeting_attachment(*, company_id: str, meeting_id: str, attachment_id: str, extension: str, content: bytes) -> StoredMeetingFile:
    directory = upload_root() / "companies" / _uuid(company_id) / "meetings" / _uuid(meeting_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    destination = directory / f"{_uuid(attachment_id)}{extension}"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o640)
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return StoredMeetingFile(destination.relative_to(upload_root()).as_posix())


def resolve_meeting_attachment(relative_path: str) -> Path:
    root = upload_root()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Invalid stored file path.")
    return candidate
