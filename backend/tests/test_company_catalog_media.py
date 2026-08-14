from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.db.base import Base
from app.modules.company_onboarding.completion import FIELD_BY_KEY as COMPANY_FIELDS
from app.modules.projects import catalog_service
from app.modules.projects.completion import FIELD_BY_KEY as PROJECT_FIELDS, calculate_completion
from app.modules.projects.models import ProjectPropertyType
from app.modules.subscriptions.schemas import PlanCreate


def test_catalog_and_media_tables_are_registered():
    assert "company_media_assets" in Base.metadata.tables
    assert "project_property_types" in Base.metadata.tables
    assert "project_property_type_media" in Base.metadata.tables
    assert "sales_asset_shares" in Base.metadata.tables


def test_project_cover_and_structured_catalog_block_completion_until_resolved():
    completion = calculate_completion({}, final_approved=False)
    blocker_keys = {item["field"] for item in completion["blockers"]}
    assert "project_cover" in blocker_keys
    assert "property_type_catalog" in blocker_keys
    assert PROJECT_FIELDS["project_cover"].requirement == "required"


def test_company_logo_is_recommended_and_can_be_deferred():
    assert COMPANY_FIELDS["company_logo"].requirement == "recommended"


def test_confirmed_property_type_requires_commercial_freshness():
    item = ProjectPropertyType(
        project_id="project-1", name="Two bedrooms", review_status="confirmed",
        available_units=4, starting_price=Decimal("350000"), currency="USD",
        inventory_updated_at=datetime.utcnow(),
    )
    assert catalog_service.is_complete(item) is True
    item.inventory_updated_at = None
    assert catalog_service.is_complete(item) is False


def test_plan_has_independent_property_type_and_unit_limits():
    plan = PlanCreate(name="Growth", max_property_types_per_project=12, max_properties_per_project=500)
    assert plan.max_property_types_per_project == 12
    assert plan.max_properties_per_project == 500


def test_catalog_migration_avoids_json_boolean_bind_tokens():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "20260814_company_catalog_media.py"
    content = migration.read_text(encoding="utf-8")
    assert ":true" not in content.casefold()
    assert "jsonb_build_object" in content
