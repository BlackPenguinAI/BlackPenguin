from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.company_onboarding.services import _labeled_company_updates, apply_field_updates


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_qa_report_multifield_message_is_split_deterministically():
    profile = CompanyProfile(profile_data={}, field_states={})
    updates = _labeled_company_updates(
        "Official company name: SR Luxury Condominium, LTD. Display name: Satya. HQ: Houston, Texas.",
        profile,
    )
    assert [(item["field"], item["value"]) for item in updates] == [
        ("official_company_name", "SR Luxury Condominium, LTD"),
        ("preferred_display_name", "Satya"),
        ("headquarters", "Houston, Texas"),
    ]


def test_document_extraction_cannot_overwrite_confirmed_user_value():
    db = _db(); company = Company(name="Tenant", country_code="US")
    db.add(company); db.flush()
    profile = CompanyProfile(
        company_id=company.id,
        profile_data={"official_company_name": "Confirmed Name"},
        field_states={"official_company_name": {"status": "confirmed", "applicable": True}},
        field_sources={},
    )
    db.add(profile); db.commit()
    result = apply_field_updates(db, profile, [{
        "field": "official_company_name", "value": "Document Name",
        "status": "extracted", "source_type": "document",
    }], allow_authoritative_statuses=False)
    assert not result.accepted
    assert result.rejected[0]["reason"] == "confirmed_value_conflict"
    assert profile.profile_data["official_company_name"] == "Confirmed Name"
