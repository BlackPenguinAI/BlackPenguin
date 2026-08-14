from app.modules.onboarding_questions import build_next_question, is_too_short, validate_onboarding_value


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
    assert question["allow_custom"] is False
    assert question["answer_actions"] == {
        "Approve profile": {"kind": "approve_profile"},
        "I need to make changes": {"kind": "request_changes"},
    }


def test_dba_question_expands_the_acronym_and_exposes_typed_actions():
    question = build_next_question(
        [{"field": "dba", "label": "DBA (Doing Business As)"}],
        final_prompt="Approve",
        profile_data={"preferred_display_name": "CBH Homes"},
    )

    assert "DBA (Doing Business As)" in question["prompt"]
    assert question["help_text"].startswith("A DBA (Doing Business As)")
    assert question["answer_actions"]["Yes — use CBH Homes"] == {
        "kind": "copy_field",
        "source_field": "preferred_display_name",
    }
    assert question["answer_actions"]["No DBA — not applicable"] == {
        "kind": "not_applicable",
    }


def test_company_short_description_accepts_a_concise_complete_sentence():
    value = "Idaho's #1 Builder, building homes since 1992."

    assert validate_onboarding_value("approved_short_company_description", value) is None
    question = build_next_question(
        [{"field": "approved_short_company_description", "label": "Approved short company description"}],
        final_prompt="Approve",
    )
    assert question["minimum_words"] is None
    assert question["minimum_characters"] == 25


def test_company_short_description_rejects_an_incomplete_fragment():
    validation = validate_onboarding_value("approved_short_company_description", "Home builder")

    assert validation == {
        "code": "minimum_characters",
        "field": "approved_short_company_description",
        "message": "Enter at least 25 characters.",
        "minimum_characters": 25,
    }


def test_official_website_requires_the_structured_contract():
    assert validate_onboarding_value(
        "official_corporate_website", {"exists": True, "url": "https://cbhhomes.com/"},
    ) is None
    assert validate_onboarding_value(
        "official_corporate_website", {"exists": False, "url": None},
    ) is None
    assert validate_onboarding_value(
        "official_corporate_website", {"exists": True, "url": "cbhhomes.com"},
    )["code"] == "invalid_website"


def test_project_sales_strategy_questions_offer_editable_examples():
    for field in ("target_audience", "value_proposition", "key_differentiators", "qualification_rules"):
        question = build_next_question(
            [{"field": field, "label": field.replace("_", " ").title()}],
            final_prompt="Approve",
            profile_data={"project_type": "Single-family", "city": "Miami", "amenities": ["Pool"]},
        )
        assert question["examples"]
        assert question["allow_custom"] is True
        assert question["input_type"] == "long_text"


def test_project_operational_steps_use_structured_contracts():
    team = build_next_question(
        [{"field": "sales_contacts", "label": "Sales contacts"}], final_prompt="Approve",
    )
    assert team["input_type"] == "project_sales_team"
    assert team["options"] == ["Configure sales team later"]

    routing = build_next_question(
        [{"field": "appointment_routing", "label": "Appointment routing"}], final_prompt="Approve",
    )
    assert routing["input_type"] == "system_managed"
    assert routing["options"] == ["Continue with round robin"]

    meta = build_next_question(
        [{"field": "campaigns_defined", "label": "Associated campaigns"}], final_prompt="Approve",
    )
    assert meta["input_type"] == "meta_lead_setup"
    assert "Page ID" in (meta["help_text"] or "")


def test_ai_sales_authorization_requires_the_explicit_consent_card():
    question = build_next_question(
        [{"field": "sales_authorization", "label": "Authorization for AI-assisted sales"}],
        final_prompt="Approve",
    )

    assert question["input_type"] == "ai_sales_authorization"
    assert question["options"] == []
    assert question["allow_custom"] is False
    assert "contact, qualify, follow up" in (question["help_text"] or "")
