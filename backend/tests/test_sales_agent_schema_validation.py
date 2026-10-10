import pytest
from pydantic import ValidationError

from app.modules.sales_agent.schemas import LiveLeadForm


def test_short_phone_uses_the_domain_message_instead_of_pydantic_length_copy():
    with pytest.raises(ValidationError) as exc_info:
        LiveLeadForm(
            first_name="QA",
            last_name="Tester",
            phone="12345",
            email="qa@example.com",
            consent=True,
        )

    errors = exc_info.value.errors()
    assert errors[0]["loc"] == ("phone",)
    assert "Enter a valid phone number" in errors[0]["msg"]
    assert "at least 7 characters" not in errors[0]["msg"]


def test_live_lead_accepts_a_formatted_valid_phone():
    lead = LiveLeadForm(
        first_name="QA",
        last_name="Tester",
        phone="+1 (917) 528-4269",
        email="qa@example.com",
        consent=True,
    )

    assert lead.phone == "+19175284269"
