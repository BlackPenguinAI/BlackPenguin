from app.modules.projects.completion import FIELDS, calculate_completion
from app.modules.projects.schemas import ProjectOverviewResponse
from app.modules.projects.services import format_overview_money, overview_address
from app.modules.sales_crm.schemas import SalesReportResponse


def _resolved_states():
    return {
        field.key: {"status": "confirmed", "applicable": True}
        for field in FIELDS
        if field.requirement in {"required", "conditionally_required"}
    }


def test_required_data_needs_explicit_final_confirmation():
    result = calculate_completion(_resolved_states(), final_approved=False)

    assert result["required_fields_complete"] is True
    assert result["ready_for_confirmation"] is True
    assert result["can_complete"] is False


def test_explicit_approval_completes_onboarding():
    result = calculate_completion(_resolved_states(), final_approved=True)

    assert result["required_fields_complete"] is True
    assert result["ready_for_confirmation"] is False
    assert result["can_complete"] is True


def test_sales_report_accepts_honest_pending_metrics():
    report = SalesReportResponse(
        inventory_status=None,
        total_revenue=None,
        target_roi=None,
        unit_inventory=[],
        leads_map=[],
    )

    assert report.calculation_status == "pending"
    assert report.total_revenue is None
    assert report.target_roi is None


def test_overview_accepts_pending_inventory_and_location():
    overview = ProjectOverviewResponse(
        id="project-1",
        name="Project One",
        metrics=[],
        inventory=[],
        location={"address": None, "latitude": None, "longitude": None},
        market_intelligence={"status": "pending"},
        data_completeness={"percentage": 100, "onboarding_status": "completed"},
    )

    assert overview.cover_image_url is None
    assert overview.inventory == []


def test_overview_formats_commercial_prices_in_english():
    assert format_overview_money("1500000.0", "usd") == "USD 1,500,000"
    assert format_overview_money("1499.95", "USD") == "USD 1,499.95"


def test_overview_does_not_duplicate_city_or_country_already_in_address():
    assert overview_address(
        "5000 Biscayne Blvd, Miami, Florida 33137, United States",
        "Miami",
        "US",
    ) == "5000 Biscayne Blvd, Miami, Florida 33137, United States"
    assert overview_address("5000 Biscayne Blvd", "Miami", "United States") == (
        "5000 Biscayne Blvd, Miami, United States"
    )
