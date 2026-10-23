from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.onboarding_questions import validate_onboarding_value
from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType, ProjectUnit
from app.modules.sales_agent.commercial_context import (
    build_commercial_context,
    confirmed_profile_facts,
)
from app.modules.sales_agent.response_policy import (
    appointment_intent_present,
    complete_requested_commercial_topics,
    plain_channel_text,
    remove_unsolicited_appointment_offer,
    repeats_recent_assistant_reply,
)
from app.modules.sales_agent.live_service import _confirmed_handoff_reply


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_only_affirmative_confirmed_profile_facts_reach_the_agent():
    profile = type("Profile", (), {
        "profile_data": {
            "starting_price": 280000,
            "promotions": "Old promotion",
            "maximum_price": 320000,
        },
        "field_states": {
            "starting_price": {"status": "confirmed", "applicable": True},
            "promotions": {"status": "not_applicable", "applicable": False},
            "maximum_price": {"status": "pending_confirmation", "applicable": True},
        },
    })()

    assert confirmed_profile_facts(profile) == {"starting_price": 280000}


def test_individual_units_take_precedence_and_conflicts_are_explicit():
    db = _db()
    company = Company(name="Dolcan")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Dolcan Homes")
    profile = ProjectProfile(
        project=project,
        profile_data={"available_inventory": 6, "typologies": ["3 bedrooms", "4+ bedrooms"]},
        field_states={
            "available_inventory": {"status": "confirmed", "applicable": True},
            "typologies": {"status": "confirmed", "applicable": True},
        },
    )
    product = ProjectPropertyType(
        project=project, name="3BR Single-Family Home", available_units=6,
        starting_price=280000, currency="USD", review_status="confirmed",
        inventory_updated_at=datetime(2026, 10, 18),
    )
    db.add_all([project, profile, product]); db.flush()
    db.add_all([
        ProjectUnit(project=project, unit_code="A", typology=product.name, status="available"),
        ProjectUnit(project=project, unit_code="B", typology=product.name, status="sold"),
    ])
    db.commit()

    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1",
    )

    assert context["inventory_source"] == "individual_units"
    assert [item["unit_code"] for item in context["inventory"]] == ["A", "B"]
    assert {item["code"] for item in context["data_conflicts"]} == {
        "inventory_count_mismatch", "profile_typology_missing_from_catalog",
    }
    assert context["data_conflicts"][0]["canonical_value"] == 1


def test_future_inventory_dates_are_withheld_and_reported_as_conflicts():
    db = _db()
    company = Company(name="Coahuila Company"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Coahuila 34")
    project.profile = ProjectProfile(profile_data={}, field_states={})
    product = ProjectPropertyType(
        project=project, name="Two bedroom", bedrooms=2, review_status="confirmed",
        inventory_updated_at=datetime(2099, 10, 31),
    )
    db.add_all([project, product]); db.commit()

    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1",
    )

    assert context["property_types"][0]["inventory_updated_at"] is None
    assert context["inventory_updated_at"] is None
    assert {item["code"] for item in context["data_conflicts"]} == {"future_inventory_timestamp"}


def test_exact_address_rejects_embedded_commercial_facts():
    error = validate_onboarding_value(
        "exact_address",
        "2600 N Conway Ave, Mission, TX 78574. Homes are 3-4 bedrooms; prices from $280,000.",
    )

    assert error is not None
    assert error["code"] == "mixed_field_content"
    assert validate_onboarding_value("exact_address", "2600 N Conway Ave, Mission, TX 78574") is None


def test_channel_policy_removes_markdown_and_blocks_unsolicited_appointment_actions():
    assert plain_channel_text("**Available homes**\n- Three bedrooms") == "Available homes\n• Three bedrooms"
    history = [
        {"role": "assistant", "content": "Hi Alex, thanks for your interest."},
        {"role": "user", "content": "Hi"},
    ]
    assert repeats_recent_assistant_reply("Hi Alex, thanks for your interest.", history)
    assert not appointment_intent_present("What are the prices?", history)
    assert appointment_intent_present("Can I schedule a visit?", history)
    assert remove_unsolicited_appointment_offer(
        "Homes start at $280,000. Would you like to schedule a visit?"
    ) == "Homes start at $280,000."


def test_handoff_copy_confirms_the_persisted_action_instead_of_showing_a_dead_end():
    assert "callback request" in _confirmed_handoff_reply(
        "Can somebody call me?", [{"type": "request_callback"}],
    )
    material_reply = _confirmed_handoff_reply(
        "Can you email the brochure?", [{"type": "request_human_review"}],
    )
    assert "approved document" in material_reply
    assert "Sales team" in material_reply


def test_multi_topic_question_is_completed_from_confirmed_context():
    reply, supplemented = complete_requested_commercial_topics(
        "We offer three-bedroom homes.",
        inbound="What types are available, how many, what are the prices, and do you offer financing?",
        actions=[],
        commercial={
            "inventory_source": "property_type_catalog",
            "inventory": [{"property_type": "3BR", "available_units": 5, "starting_price": 280000, "currency": "USD"}],
            "property_types": [{"property_type": "3BR"}],
            "confirmed_project_facts": {"payment_methods": "Cash and bank financing"},
        },
    )
    assert "Current availability: 5 homes." in reply
    assert "Confirmed starting price: USD 280,000." in reply
    assert "Payment and financing: Cash and bank financing." in reply
    assert {"inventory", "pricing", "financing"}.issubset(supplemented)

