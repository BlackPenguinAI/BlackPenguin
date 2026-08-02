from app.modules.projects.completion import FIELDS, calculate_completion, normalize_field_key


def test_required_and_applicable_fields_drive_completion():
    states = {}
    for field in FIELDS:
        if field.requirement == "required":
            states[field.key] = {"status": "confirmed", "applicable": True}
        elif field.requirement == "conditionally_required":
            states[field.key] = {"status": "not_applicable", "applicable": False}

    result = calculate_completion(states, final_approved=True)

    assert result["percentage"] == 100
    assert result["can_complete"] is True
    assert result["sales_activation_status"] == "ready"


def test_pending_source_proposal_does_not_count_as_complete():
    states = {
        field.key: {
            "status": "pending_confirmation" if field.key == "starting_price" else "confirmed",
            "applicable": True,
        }
        for field in FIELDS if field.requirement == "required"
    }
    for field in FIELDS:
        if field.requirement == "conditionally_required":
            states[field.key] = {"status": "not_applicable", "applicable": False}

    result = calculate_completion(states, final_approved=True)

    assert result["can_complete"] is False
    assert any(item["field"] == "starting_price" for item in result["blockers"])


def test_aliases_are_normalized_but_unknown_fields_are_rejected():
    assert normalize_field_key("price from") == "starting_price"
    assert normalize_field_key("available_units") == "available_inventory"
    assert normalize_field_key("tenant_secret") is None
