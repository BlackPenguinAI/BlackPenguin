from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from app.core.config import settings


SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")


@dataclass(frozen=True)
class StoredProjectFile:
    relative_path: str
    stored_filename: str


def upload_root() -> Path:
    root = Path(settings.PROJECT_UPLOAD_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    return root


def _safe_segment(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid storage identifier.") from exc


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if SAFE_EXTENSION.fullmatch(suffix) else ""


def project_directory(company_id: str, project_id: str) -> Path:
    return upload_root() / "companies" / _safe_segment(company_id) / "projects" / _safe_segment(project_id)


def store_project_file(
    *, company_id: str, project_id: str, source_id: str, original_filename: str, content: bytes,
) -> StoredProjectFile:
    source_directory = project_directory(company_id, project_id) / "sources" / _safe_segment(source_id)
    source_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    stored_filename = f"original{_extension(original_filename)}"
    destination = source_directory / stored_filename
    descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=source_directory)
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
    return StoredProjectFile(
        relative_path=destination.relative_to(upload_root()).as_posix(),
        stored_filename=stored_filename,
    )


def resolve_project_file(relative_path: str) -> Path:
    root = upload_root()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Invalid stored file path.")
    return candidate


def quarantine_project_files(company_id: str, project_id: str) -> tuple[Path, Path] | None:
    source = project_directory(company_id, project_id)
    if not source.exists():
        return None
    quarantine = upload_root() / ".trash" / str(uuid.uuid4())
    quarantine.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    os.replace(source, quarantine)
    return source, quarantine


def restore_quarantined_files(move: tuple[Path, Path] | None) -> None:
    if not move:
        return
    destination, quarantine = move
    if quarantine.exists():
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        os.replace(quarantine, destination)


def purge_quarantined_files(move: tuple[Path, Path] | None) -> None:
    if move and move[1].exists():
        try:
            shutil.rmtree(move[1])
        except OSError:
            # The database deletion already committed. Leave the isolated trash
            # directory for an operational cleanup job instead of failing the API.
            pass
