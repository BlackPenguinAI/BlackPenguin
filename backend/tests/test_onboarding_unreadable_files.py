import asyncio
from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter

from app.modules.company_onboarding import source_service as company_sources
from app.modules.onboarding_jobs.errors import (
    NO_READABLE_CONTENT_MESSAGE,
    PROTECTED_FILE_MESSAGE,
    PROTECTED_OR_LEGACY_OFFICE_MESSAGE,
    UNREADABLE_FILE_MESSAGE,
    NoReadableContentError,
    ProtectedFileError,
    ProtectedOrLegacyOfficeError,
    UnreadableFileError,
)
from app.modules.projects import source_service as project_sources


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _pdf(*, password: str | None = None) -> bytes:
    target = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if password is not None:
        writer.encrypt(password)
    writer.write(target)
    return target.getvalue()


@pytest.mark.parametrize("extractor", [company_sources._extract_bytes, project_sources._extract_bytes])
def test_password_protected_pdf_is_classified(extractor):
    with pytest.raises(ProtectedFileError) as captured:
        extractor(_pdf(password="secret"), PDF_MIME, "protected.pdf")
    assert str(captured.value) == PROTECTED_FILE_MESSAGE


@pytest.mark.parametrize("extractor", [company_sources._extract_bytes, project_sources._extract_bytes])
def test_empty_password_pdf_can_be_opened(extractor):
    assert extractor(_pdf(password=""), PDF_MIME, "restricted.pdf") == ""


@pytest.mark.parametrize("extractor", [company_sources._extract_bytes, project_sources._extract_bytes])
def test_corrupt_pdf_is_unreadable(extractor):
    with pytest.raises(UnreadableFileError) as captured:
        extractor(b"%PDF-1.7\ncorrupt", PDF_MIME, "corrupt.pdf")
    assert str(captured.value) == UNREADABLE_FILE_MESSAGE


@pytest.mark.parametrize(
    ("validator", "mime_type"),
    [
        (company_sources._validate_signature, DOCX_MIME),
        (project_sources._validate_signature, DOCX_MIME),
        (project_sources._validate_signature, XLSX_MIME),
    ],
)
def test_ole_office_file_is_protected_or_legacy(validator, mime_type):
    with pytest.raises(ProtectedOrLegacyOfficeError) as captured:
        validator(OLE_SIGNATURE + b"legacy-office-data", mime_type)
    assert str(captured.value) == PROTECTED_OR_LEGACY_OFFICE_MESSAGE


@pytest.mark.parametrize(
    ("validator", "mime_type"),
    [
        (company_sources._validate_signature, DOCX_MIME),
        (project_sources._validate_signature, DOCX_MIME),
        (project_sources._validate_signature, XLSX_MIME),
    ],
)
def test_corrupt_office_file_is_unreadable(validator, mime_type):
    with pytest.raises(UnreadableFileError):
        validator(b"PK-not-a-real-zip", mime_type)


def test_scanned_company_pdf_without_text_has_public_classification():
    source = Mock()
    with pytest.raises(NoReadableContentError) as captured:
        asyncio.run(company_sources._finish_source(Mock(), source, ""))
    assert str(captured.value) == NO_READABLE_CONTENT_MESSAGE


def test_scanned_project_pdf_without_text_has_public_classification():
    source = Mock()
    with pytest.raises(NoReadableContentError) as captured:
        asyncio.run(project_sources._finish_source(Mock(), source, text=""))
    assert str(captured.value) == NO_READABLE_CONTENT_MESSAGE


@pytest.mark.parametrize("safe_error", [company_sources._safe_error, project_sources._safe_error])
def test_internal_exception_details_are_not_exposed(safe_error):
    assert safe_error(UnreadableFileError()) == UNREADABLE_FILE_MESSAGE
    assert "PdfReadError" not in safe_error(UnreadableFileError())
