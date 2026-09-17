from types import SimpleNamespace

from app.modules.sales_crm.presentation import lead_presentation


def test_lead_presentation_flattens_nested_values_without_json_artifacts():
    lead = SimpleNamespace(phone="+15550001111", email="lead@example.com")
    result = lead_presentation(lead, {
        "selected_product": {"name": "Villa", "bedrooms": 4},
        "budget": {"minimum": 500000, "maximum": 700000, "currency": "USD"},
        "custom_answers": {"move_timing": "This year"},
    }, '{"selected_product":{"name":"Villa"},"budget":{"minimum":500000}}', [])
    rendered = str(result)
    assert result["interest"] == [
        {"label": "Property · Name", "value": "Villa"},
        {"label": "Property · Bedrooms", "value": "4"},
    ]
    assert "{'label':" in rendered  # Python's test representation is irrelevant to the UI contract.
    assert all(isinstance(row["value"], str) for group in (result["contact"], result["interest"], result["budget"], result["custom_answers"]) for row in group)
    assert '"selected_product"' not in result["summary"]
