from app.modules.onboarding_copy import conversational_acknowledgement, format_user_facing_value


def test_onboarding_values_are_rendered_without_json_syntax():
    assert format_user_facing_value(["English", "Spanish"]) == "English, Spanish"
    assert format_user_facing_value({"exists": True, "url": "https://example.com"}) == "https://example.com"


def test_acknowledgements_are_conversational_and_stable():
    accepted = [{"field": "project_name", "value": "Riverstone", "status": "confirmed"}]
    kwargs = {
        "accepted": accepted,
        "label_for": lambda _: "Project name",
        "next_prompt": "What is the project type?",
        "first_name": "Jorge",
        "scope": "Project Profile",
    }

    first = conversational_acknowledgement(**kwargs)
    second = conversational_acknowledgement(**kwargs)

    assert first == second
    assert "**Project name**" in first
    assert "**Riverstone**" in first
    assert first.endswith("What is the project type?")
    assert "I validated and updated" not in first


def test_deferred_acknowledgement_explains_that_the_step_can_be_resumed():
    response = conversational_acknowledgement(
        accepted=[{"field": "campaigns_defined", "value": None, "status": "deferred"}],
        label_for=lambda _: "Meta Lead Ads setup",
        next_prompt="Review the remaining information.",
    )

    assert "return to **Meta Lead Ads setup** later" in response
