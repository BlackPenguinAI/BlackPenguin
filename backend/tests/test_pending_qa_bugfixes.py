import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.companies.router import _timezone
from app.modules.company_onboarding import services, source_service
from app.modules.company_onboarding.models import (
    CompanyOnboardingProposal,
    CompanyOnboardingSource,
    ProposalStatus,
    SourceKind,
    SourceStatus,
)


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_company_timezone_is_validated_and_returned_by_team_contract():
    engine, db = _db()
    try:
        company = Company(name="Lima Realty", timezone="America/Lima")
        db.add(company); db.commit(); db.refresh(company)

        assert _timezone("America/Lima") == "America/Lima"
        assert services.serialize_team(db, company.id)["timezone"] == "America/Lima"
        with pytest.raises(HTTPException) as error:
            _timezone("Mars/Olympus")
        assert error.value.status_code == 422
    finally:
        db.close(); engine.dispose()


def test_corrected_company_proposal_can_be_revised_with_audit_history():
    engine, db = _db()
    try:
        company = Company(name="Revision Realty", timezone="UTC")
        db.add(company); db.flush()
        source = CompanyOnboardingSource(
            company_id=company.id, kind=SourceKind.OFFICIAL_WEBSITE,
            status=SourceStatus.READY, name="example.com", url="https://example.com",
        )
        db.add(source); db.flush()
        proposal = CompanyOnboardingProposal(
            source_id=source.id, field_key="official_company_name", value="Old Name",
            status=ProposalStatus.CORRECTED, revision=1,
            review_history=[{"revision": 1, "action": "correct", "value": "Old Name"}],
        )
        db.add(proposal); db.commit(); db.refresh(proposal)

        revised, profile = source_service.revise_proposal(
            db, proposal=proposal, company_id=company.id,
            user_id="reviewer-1", corrected_value="New Name",
        )

        assert revised.value == "New Name"
        assert revised.status == ProposalStatus.CORRECTED
        assert revised.revision == 2
        assert revised.review_history[-1]["action"] == "revise"
        assert revised.review_history[-1]["value"] == "New Name"
        assert profile.profile_data["official_company_name"] == "New Name"
    finally:
        db.close(); engine.dispose()


def test_confirmed_company_proposal_cannot_enter_revision_flow():
    engine, db = _db()
    try:
        company = Company(name="Locked Realty")
        db.add(company); db.flush()
        source = CompanyOnboardingSource(
            company_id=company.id, kind=SourceKind.OFFICIAL_WEBSITE,
            status=SourceStatus.READY, name="example.com",
        )
        db.add(source); db.flush()
        proposal = CompanyOnboardingProposal(
            source_id=source.id, field_key="official_company_name", value="Confirmed Name",
            status=ProposalStatus.CONFIRMED,
        )
        db.add(proposal); db.commit(); db.refresh(proposal)

        with pytest.raises(HTTPException) as error:
            source_service.revise_proposal(
                db, proposal=proposal, company_id=company.id,
                user_id="reviewer-1", corrected_value="Unexpected Name",
            )
        assert error.value.status_code == 409
    finally:
        db.close(); engine.dispose()
