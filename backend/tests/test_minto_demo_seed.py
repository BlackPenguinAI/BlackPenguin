from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.base  # noqa: F401 - register every model
from app.core.security import verify_password
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.companies.router import create_company_workspace
from app.modules.company_onboarding import storage_service as company_storage
from app.modules.company_onboarding.models import CompanyMediaAsset, CompanyOnboardingSource, CompanyProfile
from app.modules.demo_data.minto_seed import seed_minto_demo
from app.modules.projects import storage_service as project_storage
from app.modules.projects.models import (
    Project,
    ProjectCampaign,
    ProjectOnboardingSource,
    ProjectPropertyType,
    ProjectSourceKind,
)
from app.modules.sales_agent.simulation_service import simulation_options
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.users.models import User, UserRole


def _db(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(company_storage.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setattr(project_storage.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path / "uploads"))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_minto_seed_is_complete_idempotent_and_agent_ready(monkeypatch, tmp_path):
    engine, db = _db(monkeypatch, tmp_path)
    try:
        first = seed_minto_demo(db)
        second = seed_minto_demo(db)

        assert first["company_id"] == second["company_id"]
        company = db.query(Company).filter(Company.id == first["company_id"]).one()
        admin = db.query(User).filter(User.email == "test@minto.com").one()
        assert company.name == "Minto"
        assert admin.company_id == company.id
        assert verify_password("1234", admin.hashed_password)

        company_profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company.id).one()
        assert company_profile.final_approved is True
        assert company_profile.completion_percentage == 100
        assert db.query(CompanyOnboardingSource).filter_by(company_id=company.id).count() == 1
        assert db.query(CompanyMediaAsset).filter_by(company_id=company.id, is_primary=True).count() == 1

        projects = db.query(Project).filter(Project.company_id == company.id).order_by(Project.name).all()
        assert [item.name for item in projects] == ["East Hills Crossing", "Wildflower"]
        assert all(item.is_demo and item.onboarding_status == "completed" for item in projects)
        assert all(item.profile.final_approved and item.profile.completion_percentage == 100 for item in projects)
        assert len({item.demo_template_version for item in projects}) == 2
        assert db.query(ProjectPropertyType).count() == 6
        assert db.query(ProjectCampaign).count() == 2
        assert db.query(ProjectOnboardingSource).count() == 8

        page_sources = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.kind == ProjectSourceKind.URL
        ).all()
        assert len(page_sources) == 2
        assert all(source.mime_type == "text/html" for source in page_sources)
        assert all(source.name and source.url and source.extracted_text for source in page_sources)

        image_sources = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE
        ).all()
        assert len(image_sources) == 6
        assert all(source.name == source.original_filename for source in image_sources)
        assert all(source.mime_type.startswith("image/") for source in image_sources)
        assert all(source.size_bytes and source.sha256 for source in image_sources)

        options = simulation_options(db, company_id=company.id)
        assert {item["name"] for item in options} == {"Wildflower", "East Hills Crossing"}
        assert all(item["campaigns"] and item["products"] for item in options)
        assert {product["currency"] for item in options for product in item["products"]} == {"CAD"}
        assert all(source.storage_path for source in image_sources)
    finally:
        db.close()
        engine.dispose()


def test_creating_a_regular_company_no_longer_creates_a_demo_project(monkeypatch, tmp_path):
    engine, db = _db(monkeypatch, tmp_path)
    try:
        plan = SubscriptionPlan(name="Company Test", max_projects=5, is_active=True)
        superadmin = User(
            email="root@example.com",
            hashed_password="unused",
            role=UserRole.SUPERADMIN,
            is_active=True,
        )
        db.add_all([plan, superadmin])
        db.commit()

        with patch("app.integrations.firebase_client.ensure_firebase_ready"), patch(
            "app.modules.users.services.provision_invitation"
        ):
            company = create_company_workspace(
                name="Regular Company",
                plan_id=plan.id,
                duration_months=12,
                admin_first_name="Regular",
                admin_last_name="Admin",
                admin_email="regular@example.com",
                is_active="true",
                admin_is_active="true",
                start_date=None,
                receipt_file=None,
                db=db,
                current_user=superadmin,
            )

        assert db.query(Project).filter(Project.company_id == company.id).count() == 0
    finally:
        db.close()
        engine.dispose()
