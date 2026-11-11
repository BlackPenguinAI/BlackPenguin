"""Deterministic commercial guidance from the scoped approved snapshot only.

No financing approval, payment, sale reservation, conversion or external effect.
"""
from decimal import Decimal, InvalidOperation
import re
from .lead_profile import resolve
from .profile_intelligence import budget_cap, declared_text

VERSION='sales-commercial-policy/1.0'
DOWN_PAYMENT=re.compile(r'\b(?:down[ -]?payment|deposit|initial contribution|initial payment)\b',re.I)
TOTAL_BUDGET=re.compile(r'\b(?:total|overall|purchase|full)\s+(?:purchase\s+)?budget\b|\bbudget for (?:the )?(?:home|property|purchase)\b',re.I)


def down_payment_only(quote):
    return bool(DOWN_PAYMENT.search(quote) and not TOTAL_BUDGET.search(quote))


def _number(value):
    if value is None or isinstance(value,bool):return None
    try:
        amount=Decimal(str(value))
        return amount if amount.is_finite() and amount>=0 else None
    except (InvalidOperation,ValueError):return None


def _payment_information(commercial):
    value=commercial['confirmed_project_facts'].get('payment_methods')
    items=[value] if isinstance(value,str) else value if isinstance(value,list) else []
    # This is public onboarding knowledge, not permission to execute a payment.
    return [v.strip() for v in items if isinstance(v,str) and v.strip() and len(v)<=1000
        and not re.search(r'https?://|\bwww\.',v,re.I)]


def property_transaction_requested(text):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    request=re.search(r'\b(?:can I|could I|I want to|I would like to|please|how (?:can|do) I)\b.{0,55}\b(?:reserve|hold|separate|book|pay|make (?:a )?payment|send (?:the )?money|transfer)\b',own,re.I)
    property_or_payment=re.search(r'\b(?:unit|home|property|apartment|deposit|money|payment|bank|account|card)\b',own,re.I)
    return bool(request and property_or_payment and not re.search(r'\b(?:reserve|hold|book)\b.{0,15}\b(?:visit|appointment|viewing|time|slot)\b',own,re.I))


def only_property_transaction(text):
    return property_transaction_requested(text) and not re.search(r'\b(?:visit|appointment|viewing|tour)\b',text,re.I)


def guidance(*,text,u,commercial,lead,selected=None,holds=()):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    topics={r.topic.value for r in u.requests if r.polarity=='request'}
    current_financial=any(p.key in {'budget','financing'} and p.status=='declared' for p in u.preferences)
    commercial_turn=bool(topics & {'catalog','property_details','pricing','inventory','financing'} or current_financial or any(o.kind=='price' for o in u.objections))
    from .understanding_completeness import returns_question
    investment_question=returns_question(own)
    separation=property_transaction_requested(own)
    result={'version':VERSION,'blocks':[],'closing':'','decision':'none','alternative_ids':[]}
    def add(value):
        if value not in result['blocks']:result['blocks'].append(value)
    if investment_question:
        # No investment KPI is currently part of the typed public project facts.
        # Do not substitute loan terms or use a target ROI as a guaranteed return.
        has_figures=any(v not in (None,'',[],{}) for k,v in commercial['confirmed_project_facts'].items() if re.search(r'yield|occupancy|roi|return',k,re.I))
        add('I cannot guarantee rental yield, occupancy or investment returns.' if has_figures else 'I do not have published rental yield or occupancy figures for this project, and I cannot guarantee investment returns.')
        result.update(decision='investment_information',closing='The sales team can review investment details during a visit. Is there another property question I can help with?')
    if separation:
        add('I can help with property information and arrange a visit. Payments and reservations of a property are handled in person by the sales team; I cannot take a payment or hold a property in this chat.')
        result.update(decision='in_person_commercial_transaction',closing='Would you like to review visit options, or is there another question I can help with?')
    down=down_payment_only(own)
    if down and re.search(r'\d',own) and re.search(r'\b(?:I have|I can put|my|available)\b',own,re.I):
        add('An amount for a down payment is different from the total purchase budget.')
        result.update(decision='clarify_total_budget',closing='What total purchase budget and currency are you considering?')
    payments=_payment_information(commercial)
    finance_question='financing' in topics and not (investment_question and not re.search(r'\b(?:financing|mortgage|loan|down payment)\b',own,re.I))
    if finance_question and 'financing' not in holds:
        if payments:add('The published payment information is: '+'; '.join(payments)+'.')
        else:add('I do not have published financing or down payment terms to quote for this project.')
        add('Detailed financing and down payment conditions can be reviewed with the sales team during an in-person visit. Financing eligibility and approval are not determined in this chat.')
    profile=resolve(lead)
    cash_text=declared_text(profile,'financing')
    outright=bool(re.search(r'\b(?:cash|outright|contado)\b|\b(?:do not|don.t|no)\s+(?:need|require)\s+financing\b',cash_text,re.I))
    outright &= not bool(re.search(r'\b(?:if|suppose|or)\b|\b(?:not|no) cash\b|\b(?:cannot|can.t|don.t|do not) (?:pay|have) (?:in )?cash\b',cash_text,re.I))
    if current_financial and outright:
        add('You are considering an outright purchase, without financing.')
    cap=budget_cap(profile) if commercial_turn and not investment_question and not down and not {'pricing','catalog','inventory','property_details'} & set(holds) else None
    if commercial_turn and not investment_question and not cap and not down and (profile['current'].get('budget') or {}).get('status') in {'declared','confirmed'} and not {'pricing','catalog','inventory','property_details'} & set(holds):
        result.update(decision='clarify_budget_currency',closing='What maximum total purchase budget and currency should I use when comparing options?')
    if cap:
        amount,currency=cap;amount=Decimal(str(amount))
        individual=commercial.get('inventory_source')=='individual_units'
        rows=commercial.get('inventory',[]) if individual else commercial.get('property_types',[])
        def eligible(row):
            if individual:return str(row.get('status') or '').lower() in {'available','active','ready'}
            return row.get('available_units') is None or row.get('available_units')>0
        priced=[r for r in rows if eligible(r) and _number(r.get('price') if individual else r.get('starting_price')) is not None and r.get('currency')]
        comparable=[r for r in priced if str(r['currency']).upper()==currency]
        selected_type=next((r.get('property_type') for r in commercial.get('property_types',[]) if r['id']==selected),None)
        selected_rows=[r for r in comparable if r['id']==selected or (individual and selected_type and str(r.get('property_type') or '').casefold()==selected_type.casefold())]
        expensive=bool(selected_rows) and all(_number(r.get('price') if individual else r.get('starting_price'))>amount for r in selected_rows)
        within=[r for r in comparable if _number(r.get('price') if individual else r.get('starting_price'))<=amount]
        if not selected or expensive or (individual and selected_type and within):
            alternatives=[r for r in within if r['id']!=selected]
            if alternatives:
                result['alternative_ids']=[r['id'] for r in alternatives[:3]]
                for row in alternatives[:3]:
                    name=row.get('unit_code') or row.get('property_type')
                    price=_number(row.get('price') if individual else row.get('starting_price'))
                    add(f"{name} {'has a listed price of' if individual else 'has a published starting price of'} {price:,.2f} {currency}, within your stated total budget.")
                add('The exact property price and current availability still need confirmation.')
                result.update(decision='within_budget_alternative',closing='Would you like more details about one of these options?')
            elif comparable:
                add('I do not have a listed option within your stated total budget in this project.')
                financing=any(re.search(r'\b(?:financ\w*|mortgage|loan)\b',p,re.I) and not re.search(r'\b(?:no|not|without|unavailable)\b',p,re.I) for p in payments)
                if financing and 'financing' not in holds and not outright:
                    add('The published payment information is: '+'; '.join(payments)+'.')
                    add('Financing may be an option to discuss, but it does not guarantee approval or change the published property price.')
                    add('Detailed financing and down payment conditions can be reviewed with the sales team during an in-person visit. Financing eligibility and approval are not determined in this chat.')
                    result.update(decision='discuss_published_financing',closing='Would you like to review visit options to discuss those terms, or do you have another question?')
                else:
                    result.update(decision='no_budget_match',closing='Is there another question I can help with? If not, thank you for your interest and have a good day. You are welcome to message again.')
            elif priced and not comparable:
                add('The listed prices use a different currency from your stated budget. I cannot compare them without a budget in the listed currency; I will not assume an exchange rate.')
                result.update(decision='currency_mismatch',closing='What total budget could you consider in the currency of the listed property?')
    # Questions about payments should not be followed by an unrelated qualification gate.
    if finance_question and not result['closing']:
        result['closing']='Would you like to review visit options to discuss those details, or is there another question I can help with?'
    if u.courtesy and u.courtesy.kind in {'farewell','decline'}:result['closing']=''
    blocked='appointment' in holds or any(c.topic.value=='appointment' for c in u.constraints)
    if blocked and 'visit options' in result['closing']:result['closing']='Is there another property question I can help with?'
    return result
