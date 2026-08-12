import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.company_onboarding.completion import calculate_completion
from app.modules.company_onboarding.router import _parse_agent_response
from app.modules.company_onboarding.services import (
    deterministic_context_update,
    extract_urls,
    normalize_field_key,
    normalize_user_url,
    resolve_answer_to_question,
)
from app.modules.company_onboarding.models import SenderType
from app.modules.company_onboarding.source_service import classify_url, validate_public_url


def test_human_labels_are_normalized_to_canonical_keys():
    assert normalize_field_key("Legal Name") == "official_company_name"
    assert normalize_field_key("Preferred display name") == "preferred_display_name"
    assert normalize_field_key("unknown label") is None


def test_each_confirmed_required_field_advances_completion():
    states = {
        "official_company_name": {"status": "confirmed"},
        "preferred_display_name": {"status": "confirmed"},
        "official_corporate_website": {"status": "confirmed"},
        "headquarters": {"status": "confirmed"},
    }
    completion = calculate_completion(states)
    assert completion["required"]["completed"] == 4
    assert completion["required"]["remaining"] == 7
    assert completion["percentage"] > 0


def test_same_name_is_resolved_against_pending_display_name():
    profile = SimpleNamespace(
        profile_data={"official_company_name": "Petito Company"},
        field_states={"official_company_name": {"status": "confirmed"}},
        final_approved=False,
    )
    updates = deterministic_context_update("Same name", profile)
    assert updates[0]["field"] == "preferred_display_name"
    assert updates[0]["value"] == "Petito Company"


def test_experience_is_not_converted_to_year_established():
    profile = SimpleNamespace(profile_data={}, field_states={}, final_approved=False)
    assert deterministic_context_update("We have 10 years of experience", profile) == []


def test_short_name_answers_pending_administrator_question():
    resolved_before_admin = {
        key: {"status": "confirmed"}
        for key in (
            "official_company_name",
            "preferred_display_name",
            "official_corporate_website",
            "headquarters",
        )
    }
    profile = SimpleNamespace(profile_data={}, field_states=resolved_before_admin, final_approved=False)
    updates = deterministic_context_update("Pedro", profile)
    assert updates[0]["field"] == "primary_black_penguin_administrator"
    assert updates[0]["value"] == "Pedro"


def test_typo_in_no_website_confirmation_is_still_resolved():
    states = {
        "official_company_name": {"status": "confirmed"},
        "preferred_display_name": {"status": "confirmed"},
    }
    profile = SimpleNamespace(profile_data={}, field_states=states, final_approved=False)
    updates = deterministic_context_update("Non eexists", profile)
    assert updates[0]["field"] == "official_corporate_website"
    assert updates[0]["value"] == {"exists": False, "url": None}


def test_agent_contract_never_requires_raw_json_as_visible_message():
    raw = json.dumps(
        {
            "assistant_message": "Thanks, **Pedro**.",
            "verified_updates": [
                {"field": "primary_black_penguin_administrator", "value": "Pedro", "status": "confirmed"}
            ],
            "final_approved": False,
        }
    )
    message, updates, approved = _parse_agent_response(raw)
    assert message == "Thanks, **Pedro**."
    assert updates[0]["field"] == "primary_black_penguin_administrator"
    assert approved is False


def test_urls_are_classified_without_rejecting_supporting_sources():
    assert classify_url("https://www.linkedin.com/company/petito").value == "social_profile"
    assert classify_url("https://es.scribd.com/document/123/form").value == "online_document"


def test_private_urls_are_rejected():
    with pytest.raises(HTTPException):
        validate_public_url("http://127.0.0.1/internal")


class _QuestionQuery:
    def __init__(self, question):
        self.question = question

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.question

    def all(self):
        return [self.question]


class _QuestionDb:
    def __init__(self, question):
        self.question = question

    def query(self, *args, **kwargs):
        return _QuestionQuery(self.question)


def _resolve(field: str, answer: str, *, input_type: str = "text", data=None):
    question = SimpleNamespace(
        id="question-1",
        sender=SenderType.AI,
        ui_payload={"field": field, "input_type": input_type},
        response_payload=None,
        created_at=None,
    )
    profile = SimpleNamespace(profile_data=data or {}, field_states={}, final_approved=False)
    return resolve_answer_to_question(
        _QuestionDb(question), session_id="session-1", message_id=question.id,
        answer=answer, profile=profile,
    )


def test_direct_display_name_is_applied_to_the_linked_question():
    result = _resolve("preferred_display_name", "Bloomfield Homes")
    assert result.status == "accepted"
    assert result.updates[0]["field"] == "preferred_display_name"
    assert result.updates[0]["value"] == "Bloomfield Homes"


def test_headquarters_accepts_numbers_without_a_leading_preposition():
    result = _resolve("headquarters", "Miami 123")
    assert result.status == "accepted"
    assert result.updates[0]["value"] == "Miami 123"


def test_website_question_accepts_a_domain_without_protocol():
    result = _resolve("official_corporate_website", "The official website is cbhhomes.com", input_type="url")
    assert result.status == "accepted"
    assert result.updates[0]["value"] == {"exists": True, "url": "https://cbhhomes.com/"}


def test_url_is_not_accidentally_saved_as_company_name():
    result = _resolve("official_company_name", "https://www.minto.com/")
    assert result.status == "rejected"
    assert result.reason == "url_not_valid_for_field"


def test_chat_url_normalization_removes_tracking_and_detects_bare_domains():
    assert normalize_user_url("HTTP://WWW.CBHhomes.com/?utm_source=chat") == "https://www.cbhhomes.com/"
    assert extract_urls("Use davidsonhomes.com and https://www.minto.com/") == [
        "https://davidsonhomes.com/", "https://www.minto.com/",
    ]
