"""Current declared commercial facts own scoring; history/demographics never do."""
import re
import math
from .lead_profile import resolve, known
from app.modules.sales_crm.models import LeadScoreSnapshot, LeadSegmentAssignment

VERSION = 'sales-declared-signals/1.0'
NEGATIVE = re.compile(r"\b(?:no|not|never|don't|do not|isn't|wasn't|cannot|can't|unsure|maybe|might|if)\b", re.I)


def declared_text(profile,field,*,positive=False):
    row=profile['current'].get(field) or {}
    trusted={'meta_form','source_answer','manual_registration','active_conversation','approved_catalog_selection','staff_verified'}
    if row.get('status') not in {'declared','confirmed'} or row.get('source') not in trusted:return ''
    if row.get('source')!='staff_verified' and not row.get('evidence'):return ''
    value=row.get('value')
    text=value.casefold() if isinstance(value,str) else ''
    return '' if positive and NEGATIVE.search(text) else text


def segment_for(lead):
    """Pure projection, including before the first turn after an upgrade."""
    profile=resolve(lead)
    from .understanding_contract import BUYER_SEGMENTS
    matches=set()
    for field in ('buyer_type','motivation'):
        row=profile['current'][field]
        if row.get('status') not in {'declared','confirmed'}:continue
        if row.get('polarity')=='negative' or row.get('classification_blocked'):continue
        if row.get('source') not in {'meta_form','source_answer','manual_registration','active_conversation','staff_verified'}:continue
        # A canonical form answer is already an explicit selection. Free-text
        # answers require the interpreter's annotation of this exact current record.
        segment=row.get('normalized_segment') or row.get('value')
        if isinstance(segment,str) and segment in BUYER_SEGMENTS:matches.add(segment)
    return next(iter(matches)) if len(matches)==1 else None


def budget_cap(profile):
    """An explicit amount and currency, never a currency-only or ambiguous prefill."""
    def value(field):
        row=profile['current'].get(field) or {}
        if row.get('status') not in {'declared','confirmed'}:return None
        if row.get('source') not in {'meta_form','source_answer','manual_registration','active_conversation','staff_verified'}:return None
        return row.get('value')
    def numeric(raw):
        if isinstance(raw,bool):return None
        try:
            amount=float(str(raw).replace(',',''))
            return amount if math.isfinite(amount) and amount>=0 else None
        except (TypeError,ValueError,OverflowError):return None
    raw=value('budget')
    currency=None;amount=None
    if isinstance(raw,dict):
        amount=numeric(raw.get('maximum',raw.get('max',raw.get('amount'))))
        currency=raw.get('currency')
    elif isinstance(raw,str) and not NEGATIVE.search(re.sub(
        r"\b(?:I\s+)?(?:do not|don't|no)\s+(?:need|require)\s+(?:any\s+)?financing\b",'',raw,flags=re.I)):
        from .commercial_policy import down_payment_only
        if down_payment_only(raw):return None
        matches=list(re.finditer(r'\b([A-Z]{3})\s*([0-9][0-9,]*(?:\.[0-9]+)?)\b|\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{3})\b',raw,re.I))
        if len(matches)==1 and len(re.findall(r'\d[\d,]*(?:\.\d+)?',raw))==1:
            match=matches[0];currency=(match[1] or match[4]);amount=numeric(match[2] or match[3])
    if amount is None:
        amount=numeric(value('budget_maximum'))
        currency=value('budget_currency')
    if amount is not None and isinstance(currency,str) and re.fullmatch('[A-Za-z]{3}',currency):
        return amount,currency.upper()
    return None


def update(db, lead, *, commercial, message_count, scoring_config=None):
    profile = resolve(lead)
    def text(field):
        return declared_text(profile,field)
    def positive(field):
        value = text(field)
        return value if not NEGATIVE.search(value) else ''
    config = scoring_config or {}
    def weight(key, default):
        try:return max(0, min(100, int(config.get(key, default))))
        except (TypeError, ValueError, OverflowError):return default
    timeline = positive('purchase_timeline')
    soon = bool(re.search(r'\b(?:this|next) month\b|\b(?:[1-9]|[1-8][0-9]|90) days?\b|\b[1-3] months?\b', timeline))
    financing = positive('financing')
    ready = bool(re.search(r'\b(?:pre[- ]?approved|cash buyer|paying cash|buying with cash)\b', financing))
    interest = profile['current'].get('property_interest') or {}
    chosen_id = (interest.get('source_ref') or {}).get('property_type_id') if known(profile,'property_interest') else None
    chosen_unit = (interest.get('source_ref') or {}).get('unit_id') if known(profile,'property_interest') else None
    option = next((v for v in commercial['inventory'] if v['id'] == chosen_unit), None) if chosen_unit else next((v for v in commercial['property_types'] if v['id'] == chosen_id), None)
    # No numerical amount/wealth is inferred from age, occupation or free history.
    # A fit signal requires an explicit currency and an approved price for the focus.
    amount = budget_cap(profile)
    fits = False
    if amount and option:
        maximum,currency=amount
        price = option.get('price') if chosen_unit else option.get('starting_price')
        fits = price is not None and currency == option.get('currency') and maximum >= float(price)
    factors = {
        'timeline': weight('timeline',20) if soon else 0,
        'financial_readiness': weight('financial_readiness',20) if ready else 0,
        'budget_fit': weight('budget_fit',20) if fits else 0,
        'engagement': min(weight('engagement',15),max(0,message_count)*3),
        'decision_authority': weight('decision_authority',15) if re.search(r'\b(?:i decide|decide alone|my decision|we decide|decide together)\b',positive('decision_structure')) else 0,
        'specificity': weight('specificity',10) if any(positive(f) for f in ('property_interest','bedrooms','bathrooms','needs')) else 0,
        'appointment_intent': weight('appointment_intent',35) if positive('visit_readiness') and (
            (profile['current']['visit_readiness'].get('source_ref') or {}).get('intent')=='explicit_visit'
            or re.search(r'\b(?:yes|ready|want|would like|interested)\b',positive('visit_readiness'))) else 0,
    }
    total = max(0,min(100,sum(factors.values())))
    tier = 'hot' if total >= weight('hot_threshold',70) else 'warm' if total >= weight('warm_threshold',40) else 'cold'
    snapshot = LeadScoreSnapshot(lead_id=lead.id,total_score=total,assigned_tier=tier,
                                 factor_breakdown=factors,scoring_version=VERSION)
    lead.intent_score, lead.intent_tier = total/100, tier
    # Only current explicit buyer intent/motivation can select a playbook.
    # Ambiguous or withdrawn intent removes a previous assignment; no stale persona.
    segment = segment_for(lead)
    current = db.query(LeadSegmentAssignment).filter_by(lead_id=lead.id,is_current=True).all()
    valid = len(current)==1 and current[0].segment==segment and current[0].strategy_version==VERSION
    if not valid:
        for row in current:row.is_current=False
        if segment:
            reasons = [{'field': f,'record_id':profile['current'][f]['id'],
                        'source':profile['current'][f]['source']} for f in ('buyer_type','motivation') if positive(f)]
            db.add(LeadSegmentAssignment(lead_id=lead.id,segment=segment,confidence=.9,
                                        reasons=reasons,strategy_version=VERSION,is_current=True))
    lead.assigned_segment=segment
    lead.buyer_type='investor' if segment and segment.endswith('investor') or segment=='portfolio_diversification' else 'end_user' if segment else None
    db.add_all([lead,snapshot])
    return snapshot
