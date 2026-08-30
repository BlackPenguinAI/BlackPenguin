"""Deterministic Lead Record updates used by both simulation and live SMS."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.sales_agent.segment_strategies import SEGMENT_STRATEGIES, STRATEGY_VERSION

from .models import Lead, LeadObjection, LeadScoreSnapshot, LeadSegmentAssignment


SCORING_VERSION = "intent-score-v1"


def _text(lead: Lead, conversation_text: str) -> str:
    form = " ".join(str(value) for value in (lead.meta_form_data or {}).values())
    return f"{form} {lead.qualification_summary or ''} {conversation_text}".casefold()


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
    factors = {
        "timeline": 20 if re.search(r"\b(30|60|90) days?\b|this month|next month|<90", text) else 10 if "month" in text else 0,
        "financial_readiness": 20 if any(term in text for term in ("pre-approved", "preapproved", "cash buyer", "paying cash")) else 10 if any(term in text for term in ("financing", "mortgage", "loan")) else 0,
        "budget_fit": 20 if any(key in (lead.meta_form_data or {}) for key in ("budget", "budget_min", "budget_max")) else 0,
        "engagement": min(15, message_count * 3),
        "decision_authority": 15 if any(term in text for term in ("i decide", "decide alone", "my decision")) else 7 if any(term in text for term in ("partner", "family", "spouse")) else 0,
        "specificity": 10 if any(term in text for term in ("bedroom", "unit", "tower", "phase", "floor", "m2", "sq ft")) else 0,
    }
    total = max(0, min(100, sum(factors.values())))
    tier = "hot" if total >= 70 else "warm" if total >= 40 else "cold"
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
    if objection:
        lead.pipeline_stage = "S07_OBJECTION"
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
