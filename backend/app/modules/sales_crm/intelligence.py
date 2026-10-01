"""Deterministic Lead Record updates used by both simulation and live SMS."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ai_core.services import get_ai_config
from app.modules.sales_agent.segment_strategies import SEGMENT_STRATEGIES, STRATEGY_VERSION

from .models import Lead, LeadObjection, LeadScoreSnapshot, LeadSegmentAssignment


SCORING_VERSION = "intent-score-v1"

PROFILE_FACT_ALIASES = {
    "budget_min": "budget_minimum",
    "minimum_budget": "budget_minimum",
    "budget_max": "budget_maximum",
    "maximum_budget": "budget_maximum",
    "currency": "budget_currency",
    "product": "property_interest",
    "product_interest": "property_interest",
    "property_type": "property_interest",
    "timeline": "purchase_timeline",
    "location": "location_preference",
}
PROFILE_FACT_KEYS = {
    "budget", "budget_minimum", "budget_maximum", "budget_currency",
    "property_interest", "bedrooms", "bathrooms", "location_preference",
    "purchase_timeline", "financing", "buyer_type", "motivation",
    "decision_structure", "move_in_timing",
}


def _fact_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return PROFILE_FACT_ALIASES.get(normalized, normalized)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in list(value)[:40]]
    return str(value)


def initial_lead_profile(
    *, product: dict | None = None, budget: dict | None = None,
    custom_answers: dict | None = None, source: str,
) -> dict:
    """Build a versioned profile without turning source-specific questions into columns."""
    captured_at = datetime.utcnow().isoformat() + "Z"
    facts: dict[str, dict] = {}
    if product:
        facts["property_interest"] = {
            "value": _json_value(product), "source": source,
            "captured_at": captured_at, "confirmed": source == "manual_registration",
        }
    if budget and any(value is not None for value in budget.values()):
        facts["budget"] = {
            "value": _json_value(budget), "source": source,
            "captured_at": captured_at, "confirmed": source == "manual_registration",
        }
    answers = [
        {"key": _fact_key(key), "label": str(key), "value": _json_value(value), "source": source}
        for key, value in (custom_answers or {}).items()
    ]
    return {"schema_version": 1, "facts": facts, "source_answers": answers}


def merge_extracted_facts(
    lead: Lead, facts: list[dict] | None, *, evidence: str,
    source: str = "agent_conversation",
) -> dict:
    """Persist explicit model facts with provenance; unknown keys never mutate the profile."""
    profile = dict(lead.lead_profile_data or {})
    stored = dict(profile.get("facts") or {})
    captured_at = datetime.utcnow().isoformat() + "Z"
    for item in facts or []:
        if not isinstance(item, dict):
            continue
        key = _fact_key(item.get("key") or item.get("field") or item.get("name") or item.get("fact"))
        if key not in PROFILE_FACT_KEYS or "value" not in item:
            continue
        stored[key] = {
            "value": _json_value(item.get("value")),
            "source": source,
            "captured_at": captured_at,
            "confirmed": True,
            "evidence": evidence[:500],
        }
    profile.update({"schema_version": 1, "facts": stored})
    profile.setdefault("source_answers", [])
    lead.lead_profile_data = profile
    lead.qualification_summary = lead_profile_summary(profile)
    return profile


def lead_profile_summary(profile: dict) -> str | None:
    facts = profile.get("facts") if isinstance(profile, dict) else {}
    if not isinstance(facts, dict) or not facts:
        return None
    labels = {
        "property_interest": "Property interest", "budget": "Budget",
        "budget_minimum": "Minimum budget", "budget_maximum": "Maximum budget",
        "budget_currency": "Currency", "bedrooms": "Bedrooms", "bathrooms": "Bathrooms",
        "location_preference": "Location preference", "purchase_timeline": "Purchase timeline",
        "financing": "Financing", "buyer_type": "Buyer type", "motivation": "Motivation",
        "decision_structure": "Decision structure", "move_in_timing": "Move-in timing",
    }
    parts = []
    for key, item in facts.items():
        if key not in labels or not isinstance(item, dict):
            continue
        value = item.get("value")
        rendered = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)
        parts.append(f"{labels[key]}: {rendered}")
    return "; ".join(parts) or None


def _text(lead: Lead, conversation_text: str) -> str:
    form = " ".join(str(value) for value in (lead.meta_form_data or {}).values())
    profile = json.dumps(lead.lead_profile_data or {}, ensure_ascii=False, default=str)
    return f"{form} {profile} {lead.qualification_summary or ''} {conversation_text}".casefold()


def assign_segment(db: Session, lead: Lead, conversation_text: str) -> LeadSegmentAssignment | None:
    text = _text(lead, conversation_text)
    rules = [
        ("relocation", ("relocat", "moving to", "move date", "job transfer", "another city", "another country")),
        ("rental_yield_investor", ("rental income", "airbnb", "cap rate", "occupancy", "cash flow", "yield")),
        ("appreciation_resale_investor", ("appreciation", "resale", "assignment", "flip", "phase pricing")),
        ("portfolio_diversification", ("diversif", "foreign investor", "fideicomiso", "paying cash", "portfolio")),
        ("move_up_buyer", ("sell my home", "current home", "more space", "upgrade", "move up")),
        ("downsizing", ("less maintenance", "simplif", "downsizing", "security", "smaller home")),
        ("first_time_buyer", ("first home", "first-time", "first time", "mortgage pre-approval", "down payment")),
    ]
    match = next(((segment, [term for term in terms if term in text]) for segment, terms in rules if any(term in text for term in terms)), None)
    if not match:
        return None
    segment, reasons = match
    current = db.query(LeadSegmentAssignment).filter(
        LeadSegmentAssignment.lead_id == lead.id,
        LeadSegmentAssignment.is_current.is_(True),
    ).first()
    if current and current.segment == segment:
        return current
    db.query(LeadSegmentAssignment).filter(
        LeadSegmentAssignment.lead_id == lead.id,
        LeadSegmentAssignment.is_current.is_(True),
    ).update({LeadSegmentAssignment.is_current: False}, synchronize_session=False)
    assignment = LeadSegmentAssignment(
        lead_id=lead.id, segment=segment, confidence=min(0.95, 0.65 + 0.1 * len(reasons)),
        reasons=reasons, strategy_version=STRATEGY_VERSION, is_current=True,
    )
    lead.assigned_segment = segment
    lead.buyer_type = "investor" if "investor" in segment else "end_user"
    db.add_all([lead, assignment])
    return assignment


def record_objection(db: Session, lead: Lead, inbound_text: str) -> LeadObjection | None:
    text = inbound_text.casefold()
    rules = {
        "price": ("too expensive", "price is high", "over budget", "costs too much", "muy caro", "precio"),
        "timing": ("not ready", "later", "next year", "too soon", "todavía no", "más adelante"),
        "comparison": ("compare", "other project", "another property", "otra propiedad", "comparando"),
        "trust": ("not sure this is real", "don't trust", "scam", "confianza", "estafa"),
        "approval": ("ask my partner", "ask my family", "need approval", "consultar con", "hablar con mi"),
    }
    objection_type = next((kind for kind, terms in rules.items() if any(term in text for term in terms)), None)
    if not objection_type:
        return None
    item = db.query(LeadObjection).filter(
        LeadObjection.lead_id == lead.id,
        LeadObjection.objection_type == objection_type,
        LeadObjection.status == "open",
    ).first()
    if item:
        item.occurrence_count += 1
        item.evidence = inbound_text[:2000]
        item.updated_at = datetime.utcnow()
    else:
        item = LeadObjection(lead_id=lead.id, objection_type=objection_type, evidence=inbound_text[:2000])
    db.add(item)
    return item


def calculate_score(db: Session, lead: Lead, conversation_text: str, message_count: int) -> LeadScoreSnapshot:
    text = _text(lead, conversation_text)
    config = (get_ai_config(db, None).agent_ventas or {}).get("scoring_config", {})
    weight = lambda key, fallback: int(config.get(key, fallback))
    appointment_signal = bool(re.search(
        r"\b(appointment|schedule|openings?|available\s+times?|visit|tour|showing|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"january|february|march|april|may|june|july|august|september|october|november|december)\b",
        text,
    ))
    factors = {
        "timeline": weight("timeline", 20) if re.search(r"\b(30|60|90) days?\b|this month|next month|<90|\b\d{1,2}(?:st|nd|rd|th)\b", text) else weight("timeline", 20) // 2 if "month" in text else 0,
        "financial_readiness": weight("financial_readiness", 20) if any(term in text for term in ("pre-approved", "preapproved", "cash buyer", "paying cash")) else weight("financial_readiness", 20) // 2 if any(term in text for term in ("financing", "mortgage", "loan")) else 0,
        "budget_fit": weight("budget_fit", 20) if (
            any(key in (lead.meta_form_data or {}) for key in ("budget", "budget_min", "budget_max"))
            or any(key in ((lead.lead_profile_data or {}).get("facts") or {}) for key in ("budget", "budget_minimum", "budget_maximum"))
        ) else 0,
        "engagement": min(weight("engagement", 15), message_count * 3),
        "decision_authority": weight("decision_authority", 15) if any(term in text for term in ("i decide", "decide alone", "my decision")) else weight("decision_authority", 15) // 2 if any(term in text for term in ("partner", "family", "spouse")) else 0,
        "specificity": weight("specificity", 10) if any(term in text for term in ("bedroom", "unit", "tower", "phase", "floor", "m2", "sq ft")) else 0,
        "appointment_intent": weight("appointment_intent", 35) if appointment_signal else 0,
    }
    total = max(0, min(100, sum(factors.values())))
    tier = "hot" if total >= int(config.get("hot_threshold", 70)) else "warm" if total >= int(config.get("warm_threshold", 40)) else "cold"
    snapshot = LeadScoreSnapshot(
        lead_id=lead.id, total_score=total, assigned_tier=tier,
        factor_breakdown=factors, scoring_version=SCORING_VERSION,
    )
    lead.intent_score = total / 100
    lead.intent_tier = tier
    db.add_all([lead, snapshot])
    return snapshot


def update_lead_intelligence(db: Session, lead: Lead, *, inbound_text: str, conversation_text: str, message_count: int) -> None:
    objection = record_objection(db, lead, inbound_text)
    complete_context = f"{conversation_text} {inbound_text}"
    assign_segment(db, lead, complete_context)
    snapshot = calculate_score(db, lead, complete_context, message_count)
    if objection and (objection.occurrence_count >= 2 or "not ready" in inbound_text.casefold()):
        snapshot.factor_breakdown = {**snapshot.factor_breakdown, "readiness_penalty": -max(0, snapshot.total_score - 39)}
        snapshot.total_score = min(snapshot.total_score, 39)
        lead.intent_tier = "cold"
        lead.intent_score = snapshot.total_score / 100
        snapshot.assigned_tier = "cold"
    appointment_signal = bool(re.search(
        r"\b(appointment|schedule|openings?|available\s+times?|visit|tour|showing|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"january|february|march|april|may|june|july|august|september|october|november|december)\b",
        inbound_text.casefold(),
    ))
    if objection:
        lead.pipeline_stage = "S07_OBJECTION"
    elif appointment_signal:
        lead.pipeline_stage = "S08_APPOINTMENT"
    elif lead.assigned_segment:
        lead.pipeline_stage = "S05_SEGMENTATION"
    elif message_count >= 3:
        lead.pipeline_stage = "S04_SCORING"
    else:
        lead.pipeline_stage = "S02_QUALIFICATION"
    db.add(lead)


def strategy_context(lead: Lead) -> str | None:
    strategy = SEGMENT_STRATEGIES.get(lead.assigned_segment or "")
    return strategy
