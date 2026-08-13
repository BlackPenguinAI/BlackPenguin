import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.company_onboarding.completion import FIELD_BY_KEY, calculate_completion
from app.modules.company_onboarding.router import _parse_agent_response, _workflow_stage
from app.modules.company_onboarding.services import (
    deterministic_context_update,
    extract_urls,
    get_active_question,
    normalize_field_key,
    normalize_user_url,
    resolve_answer_to_question,
    supersede_unanswered_questions,
)
from app.modules.company_onboarding.models import SenderType
from app.modules.company_onboarding.source_service import (
    _extract_bytes,
    _embedded_link_values,
    classify_url,
    validate_public_url,
)
from app.modules.onboarding_questions import build_next_question, validate_onboarding_value


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
    assert completion["required"]["remaining"] == 6
    assert completion["percentage"] > 0


def test_application_administrator_is_not_a_company_profile_field():
    assert "primary_black_penguin_administrator" not in FIELD_BY_KEY
    assert calculate_completion({})["required"]["total"] == 10


def test_sales_and_marketing_users_replace_duplicate_contact_fields():
    assert "primary_corporate_sales_contact" not in FIELD_BY_KEY
    assert "primary_corporate_marketing_contact" not in FIELD_BY_KEY
    assert FIELD_BY_KEY["public_contact_emails"].requirement == "recommended"
    assert FIELD_BY_KEY["public_contact_phones"].requirement == "recommended"
    assert FIELD_BY_KEY["corporate_social_profiles"].requirement == "recommended"
    assert calculate_completion({})["conditional"]["total"] == 5


def test_company_workflow_waits_for_required_fields_before_team():
    profile = {
        "completion": {
            "can_complete": False,
            "required": {"remaining": 1},
            "blockers": [{"field": "official_company_name"}],
        },
        "fields": [],
    }
    team = {"roles": [{"role": "assistant", "status": "missing"}]}

    assert _workflow_stage(
        profile, team, processing=False, pending_review=False, pristine=False,
    ) == "required"

    profile["completion"]["required"]["remaining"] = 0
    profile["completion"]["blockers"] = [{"field": "dba"}]
    assert _workflow_stage(
        profile, team, processing=False, pending_review=False, pristine=False,
    ) == "team"


def test_company_workflow_prioritizes_website_review_and_then_enrichment():
    profile = {
        "completion": {
            "can_complete": False,
            "required": {"remaining": 0},
            "blockers": [],
        },
        "fields": [
            {"key": "public_contact_emails", "status": "missing"},
            {"key": "public_contact_phones", "status": "confirmed"},
            {"key": "corporate_social_profiles", "status": "deferred"},
        ],
    }
    team = {"roles": [{"role": "assistant", "status": "deferred"}]}

    assert _workflow_stage(
        profile, team, processing=False, pending_review=True, pristine=False,
    ) == "website_review"
    assert _workflow_stage(
        profile, team, processing=False, pending_review=False, pristine=False,
    ) == "enrichment"

    profile["fields"][0]["status"] = "deferred"
    assert _workflow_stage(
        profile, team, processing=False, pending_review=False, pristine=False,
    ) == "approval"


def test_deferred_conditional_field_does_not_block_completion():
    states = {
        field: {"status": "confirmed"}
        for field in (
            "official_company_name", "preferred_display_name", "official_corporate_website",
            "headquarters", "primary_business_model", "core_asset_classes",
            "current_operating_footprint", "approved_short_company_description",
            "corporate_value_proposition", "corporate_differentiators",
        )
    }
    for field in ("legal_company_name", "dba", "parent_company", "additional_corporate_languages", "corporate_compliance_information"):
        states[field] = {"status": "deferred", "applicable": True}

    completion = calculate_completion(states, final_approved=True)

    assert completion["can_complete"] is True
    assert completion["percentage"] == 100


def test_conditional_questions_offer_later_and_not_applicable_actions():
    question = build_next_question(
        [{"field": "parent_company", "label": "Parent company", "status": "applicability_pending", "requirement": "conditionally_required"}],
        final_prompt="Approve",
    )
    assert question["answer_actions"]["Provide later"] == {"kind": "defer"}
    assert question["answer_actions"]["Not applicable"] == {"kind": "not_applicable"}


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
                {"field": "official_company_name", "value": "Petito", "status": "confirmed"}
            ],
            "final_approved": False,
        }
    )
    message, updates, approved = _parse_agent_response(raw)
    assert message == "Thanks, **Pedro**."
    assert updates[0]["field"] == "official_company_name"
    assert approved is False


def test_urls_are_classified_without_rejecting_supporting_sources():
    assert classify_url("https://www.linkedin.com/company/petito").value == "social_profile"
    assert classify_url("https://es.scribd.com/document/123/form").value == "online_document"


def test_html_keeps_public_contact_and_social_links_for_extraction():
    html = b'''<html><body><a href="mailto:Info@Example.com">Email</a>
        <a href="tel:+1-305-555-0100">Call</a>
        <a href="https://www.linkedin.com/company/example"><svg></svg></a></body></html>'''
    text = _extract_bytes(html, "text/html", "https://example.com")
    assert "ONBOARDING_LINK:mailto:Info@Example.com" in text
    assert "ONBOARDING_LINK:tel:+1-305-555-0100" in text
    assert "ONBOARDING_LINK:https://www.linkedin.com/company/example" in text

    values = _embedded_link_values(text)
    assert values["public_contact_emails"] == ["info@example.com"]
    assert values["public_contact_phones"] == ["+1-305-555-0100"]
    assert values["corporate_social_profiles"] == ["https://www.linkedin.com/company/example"]


def test_public_contact_and_social_values_are_validated():
    assert validate_onboarding_value("public_contact_emails", ["info@example.com"]) is None
    assert validate_onboarding_value("public_contact_phones", ["+1 305 555 0100"]) is None
    assert validate_onboarding_value("corporate_social_profiles", ["https://instagram.com/example"]) is None
    assert validate_onboarding_value("public_contact_emails", ["invalid"])["code"] == "invalid_public_contact_emails"


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


def _resolve(field: str, answer: str, *, input_type: str = "text", data=None, payload=None):
    question = SimpleNamespace(
        id="question-1",
        sender=SenderType.AI,
        ui_payload={"field": field, "input_type": input_type, **(payload or {})},
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


def test_direct_dba_answer_is_applied_without_model_inference():
    result = _resolve("dba", "CBH Homes")

    assert result.status == "accepted"
    assert result.updates[0]["field"] == "dba"
    assert result.updates[0]["value"] == "CBH Homes"
    assert result.updates[0]["applicable"] is True


def test_dba_typed_choices_copy_a_known_name_or_mark_the_field_not_applicable():
    actions = {
        "answer_actions": {
            "Yes — use CBH Homes": {"kind": "copy_field", "source_field": "preferred_display_name"},
            "No DBA — not applicable": {"kind": "not_applicable"},
        }
    }
    copied = _resolve(
        "dba", "Yes — use CBH Homes", data={"preferred_display_name": "CBH Homes"}, payload=actions,
    )
    not_applicable = _resolve("dba", "No DBA — not applicable", payload=actions)

    assert copied.updates[0]["value"] == "CBH Homes"
    assert not_applicable.updates[0]["status"] == "not_applicable"
    assert not_applicable.updates[0]["applicable"] is False


def test_missing_reply_id_recovers_the_latest_server_owned_question():
    older = SimpleNamespace(id="older", ui_payload={"field": "dba"}, response_payload=None)
    latest = SimpleNamespace(id="latest", ui_payload={"field": "dba"}, response_payload=None)

    class Query:
        def filter(self, *args, **kwargs): return self
        def order_by(self, *args, **kwargs): return self
        def all(self): return [latest, older]

    db = SimpleNamespace(query=lambda *args, **kwargs: Query())

    assert get_active_question(db, "session-1", None) is latest
    assert get_active_question(db, "session-1", "older") is latest


def test_dba_label_is_explained_in_profile_progress():
    assert FIELD_BY_KEY["dba"].label == "DBA (Doing Business As)"


def test_creating_a_new_question_supersedes_previous_unanswered_questions():
    previous = SimpleNamespace(
        id="previous", ui_payload={"field": "dba"}, response_payload=None,
    )

    class Query:
        def filter(self, *args, **kwargs): return self
        def all(self): return [previous]

    added = []
    db = SimpleNamespace(query=lambda *args, **kwargs: Query(), add=added.append)

    changed = supersede_unanswered_questions(db, "session-1")

    assert changed is True
    assert previous.response_payload["status"] == "superseded"
    assert added == [previous]


def test_refreshing_state_can_keep_and_upgrade_the_active_question():
    active = SimpleNamespace(id="active", ui_payload={"field": "dba"}, response_payload=None)
    older = SimpleNamespace(id="older", ui_payload={"field": "dba"}, response_payload=None)

    class Query:
        def filter(self, *args, **kwargs): return self
        def all(self): return [active, older]

    added = []
    db = SimpleNamespace(query=lambda *args, **kwargs: Query(), add=added.append)

    changed = supersede_unanswered_questions(db, "session-1", keep_message_id="active")

    assert changed is True
    assert active.response_payload is None
    assert older.response_payload["status"] == "superseded"
    assert added == [older]
