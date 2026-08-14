from app.modules.onboarding_questions import build_next_question
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


def test_conditional_fields_must_be_explicitly_resolved_and_can_be_deferred():
    states = {
        field.key: {"status": "confirmed", "applicable": True}
        for field in FIELDS if field.requirement == "required"
    }

    pending = calculate_completion(states)
    assert any(
        item["requirement"] == "conditionally_required"
        and item["status"] == "applicability_pending"
        for item in pending["blockers"]
    )

    for field in FIELDS:
        if field.requirement == "conditionally_required":
            states[field.key] = {"status": "deferred", "applicable": True}

    resolved = calculate_completion(states, final_approved=True)
    assert resolved["percentage"] == 100
    assert resolved["can_complete"] is True
    assert resolved["completed"] == resolved["total"]


def test_deferred_operational_fields_allow_profile_completion_but_not_sales_activation():
    states = {
        field.key: {"status": "confirmed", "applicable": True}
        for field in FIELDS if field.requirement == "required"
    }
    for field in FIELDS:
        if field.requirement == "conditionally_required":
            states[field.key] = {"status": "not_applicable", "applicable": False}
    states["sales_contacts"] = {"status": "deferred", "applicable": True}
    states["appointment_routing"] = {"status": "deferred", "applicable": True}
    states["campaigns_defined"] = {"status": "deferred", "applicable": True}
    states["meta_connection_verified"] = {"status": "deferred", "applicable": True}

    result = calculate_completion(states, final_approved=True)

    assert result["can_complete"] is True
    assert result["sales_activation_status"] == "not_ready"
    assert {item["field"] for item in result["sales_activation_blockers"]} >= {
        "sales_contacts", "appointment_routing", "campaigns_defined", "meta_connection_verified",
    }


def test_property_catalog_precedes_catalog_derived_fields():
    keys = [field.key for field in FIELDS]

    assert keys.index("property_type_catalog") < keys.index("typologies")
    assert keys.index("property_type_catalog") < keys.index("available_inventory")


def test_structure_and_compliance_questions_explain_the_expected_information():
    phases = build_next_question([{
        "field": "phases_and_towers", "label": "Phases and towers",
        "status": "applicability_pending", "requirement": "conditionally_required",
    }], final_prompt="Approve")
    compliance = build_next_question([{
        "field": "compliance_notes", "label": "Project compliance notes",
        "status": "applicability_pending", "requirement": "conditionally_required",
    }], final_prompt="Approve")

    assert "Single phase — no towers" in phases["options"]
    assert "Multiple towers or buildings" in phases["options"]
    assert compliance["input_type"] == "multi_select"
    assert "Use standard Company compliance; no Project-specific notes" in compliance["options"]
