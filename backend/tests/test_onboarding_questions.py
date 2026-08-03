from app.modules.onboarding_questions import build_next_question, is_too_short


def test_categorical_question_exposes_choices_and_custom_answer():
    question = build_next_question(
        [{"field": "project_type", "label": "Project type"}],
        final_prompt="Approve",
    )
    assert question["input_type"] == "single_select"
    assert "Condominium" in question["options"]
    assert question["allow_custom"] is True


def test_open_description_exposes_complete_examples():
    question = build_next_question(
        [{"field": "short_description", "label": "Approved short description"}],
        final_prompt="Approve",
    )
    assert question["examples"]
    assert question["minimum_words"] == 8
    assert is_too_short("short_description", "luxury") is True
    assert is_too_short(
        "short_description",
        "Luxury residences with premium amenities and exceptional services in central Miami.",
    ) is False


def test_final_question_has_explicit_approval_choices():
    question = build_next_question([], final_prompt="Review and approve the profile.")
    assert question["field"] is None
    assert question["options"] == ["Approve profile", "I need to make changes"]
