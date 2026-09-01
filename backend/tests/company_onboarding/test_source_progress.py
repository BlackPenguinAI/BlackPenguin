from datetime import datetime

from app.modules.company_onboarding.models import (
    CompanyOnboardingSource,
    SourceKind,
    SourceStatus,
)
from app.modules.company_onboarding.source_service import serialize_source


def test_source_payload_exposes_truthful_operational_progress():
    source = CompanyOnboardingSource(
        id="source-1",
        company_id="company-1",
        kind=SourceKind.OFFICIAL_WEBSITE,
        status=SourceStatus.PROCESSING,
        name="example.com",
        url="https://example.com",
        processing_stage="identifying",
        processing_detail="Identifying company facts supported by the source.",
        created_at=datetime(2026, 9, 1),
        updated_at=datetime(2026, 9, 1),
    )

    payload = serialize_source(source)

    assert payload["processing_stage"] == "identifying"
    assert payload["processing_detail"] == "Identifying company facts supported by the source."
    assert payload["status"] == "processing"
