from app.modules.demo_projects.template import FIELD_STATES, LEADS, PROFILE_DATA, UNITS
from app.modules.projects.completion import FIELDS, calculate_completion


def test_demo_template_is_really_complete():
    assert {field.key for field in FIELDS} == set(FIELD_STATES)
    assert set(PROFILE_DATA).issuperset(field.key for field in FIELDS)
    completion = calculate_completion(FIELD_STATES, final_approved=True)
    assert completion["percentage"] == 100
    assert completion["can_complete"] is True


def test_demo_template_contains_safe_operational_data():
    assert len(UNITS) == 6
    assert len(LEADS) >= 4
    assert all(email.endswith(".invalid") for _, _, email, _, _ in LEADS)
    assert "synthetic" in PROFILE_DATA["compliance_notes"].lower()
