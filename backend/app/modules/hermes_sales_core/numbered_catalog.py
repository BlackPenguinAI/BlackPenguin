"""Render an already verified property menu after a monetary guard rejection.

The model chooses the displayed subset and order. This is a presentation repair,
not a second search, intent classifier, pricing policy or commercial operation.
The caller MUST re-run the same monetary and language checks on the new text.
"""
from __future__ import annotations
import re

# Keep compound requests, comparisons, commercial actions and detailed questions
# on the ordinary fail-closed path. Only the verified catalog-list use case is
# certified by this repair. No inferred buyer preferences are persisted here.
_OTHER_REQUEST = re.compile(
    r'\b(?:also|then|compare|send|share|explain|describe|details|specifications|'
    r'book|cancel|reschedule|visit|appointment|tour|where|when|address|location|'
    r'how many|how much|why|financ\w*|mortgage|loan|payment|discount|'
    r'contact|call|email|text me|negotiat\w*|fee\w*|tax\w*)\b|[;\n]', re.I)
# Project overview is a scoped, side-effect-free catalog read. It does not
# change search_rows, menus, focus or drafts. Do not generalize this exception
# to all read tools: some of those update conversational context.
_RECONCILABLE_TOOLS = frozenset({'search_properties', 'get_project_overview'})
_CURRENCIES = frozenset({'USD','MXN','PEN','EUR','COP','BRL','CLP','ARS','CAD','GBP'})


def reconcile_numbered_catalog(reply, *, buyer_message, search_rows, menus,
                               observations, active_search, inbound_id, media_offer,
                               channel):
    """Return (canonical reply, exact new menu), or None if not provable.

    Only the *same turn's* successfully executed search and uniquely identified
    visible property menu may be used. Preserve membership/order; use approved
    prices, not model amounts or the buyer's search ceiling. No new effects.
    """
    from .commercial_turn import search_request, extracted_criteria
    from .conversation_parity import delivered_property_menu, display_name
    from .bp_operation_receipts import visible_menu
    from app.modules.sales_agent.response_policy import requested_topics, render_channel_text
    from app.modules.money import parse_amount, format_amount

    if (not isinstance(buyer_message,str) or not search_request(buyer_message) or _OTHER_REQUEST.search(buyer_message)
            or requested_topics(buyer_message)-{'property_types','inventory','pricing'}
            or media_offer or not observations
            or any(not isinstance(o,dict) or o.get('tool') not in _RECONCILABLE_TOOLS
                   or o.get('status')!='executed' or o.get('error_code') is not None
                   for o in observations)
            or not any(o.get('tool')=='search_properties' for o in observations)):
        return None
    if (not isinstance(active_search,dict) or active_search.get('source_inbound_message_id')!=inbound_id
            or not isinstance(search_rows,list) or len(menus)!=1 or menus[0].get('type')!='property'):
        return None
    # Re-prove what the customer-facing text actually contained, not just an
    # earlier proposed menu or an unordered search result.
    original=delivered_property_menu(reply,search_rows)
    if not original or original!=menus[0] or not visible_menu(reply,original):
        return None
    refs=[o['unit_id'] for o in original['options']]
    rows={r['reference']:r for r in search_rows}
    if len(rows)!=len(search_rows) or not all(ref in rows for ref in refs):
        return None
    criteria=extracted_criteria(buyer_message)
    # Independently reject contradictions with the explicit, supported buyer
    # filters. In particular, never replace an over-budget listing by quietly
    # presenting its actual (still over-budget) price.
    lines=['Here are the matching catalog options:']
    try:
        for index,ref in enumerate(refs,1):
            row=rows[ref]; name=display_name(row); currency=row.get('currency')
            if (row.get('kind') not in {'unit','property_type'} or not name or len(name)>100
                    or re.search(r'[\x00-\x1f\x7f<>\[\]`*]|https?://',name,re.I)
                    or currency not in _CURRENCIES):
                return None
            amount=parse_amount(row.get('price'))
            beds=row.get('bedrooms')
            if ('bedrooms' in criteria and beds!=criteria['bedrooms']
                    or 'bedrooms_any' in criteria and beds not in criteria['bedrooms_any']):
                return None
            if any(k in criteria for k in ('max_price_usd','min_price_usd')):
                if (currency!='USD' or ('max_price_usd' in criteria and amount>criteria['max_price_usd'])
                        or ('min_price_usd' in criteria and amount<criteria['min_price_usd'])):
                    return None
                # Respect strict under/above wording at the boundary too.
                if (('max_price_usd' in criteria and amount==criteria['max_price_usd']
                     and re.search(r'\b(?:under|below|less than)\b',buyer_message,re.I))
                    or ('min_price_usd' in criteria and amount==criteria['min_price_usd']
                        and re.search(r'\b(?:above|over)\b',buyer_message,re.I))):
                    return None
            label='starting price' if row['kind']=='property_type' else 'listing price'
            line=f'{index}. {name}: {label} {currency} {format_amount(amount)}'
            if type(beds) in (int,float) and 0<=beds<=100 and int(beds)==beds:
                line+=f'; {int(beds)} bedroom'+('s' if beds!=1 else '')
            lines.append(line)
    except (ValueError,TypeError,KeyError,OverflowError):
        return None
    lines.extend(['','Which property would you like to explore?'])
    candidate=render_channel_text('\n'.join(lines),channel)
    # A menu cannot span multiple delivery parts; leave the existing bound in
    # force and refuse here rather than emitting an unselectable menu.
    if len(candidate)>(1400 if channel=='sms' else 3500):
        return None
    menu=delivered_property_menu(candidate,search_rows)
    if not menu or [o['unit_id'] for o in menu['options']]!=refs or not visible_menu(candidate,menu):
        return None
    return candidate,menu
