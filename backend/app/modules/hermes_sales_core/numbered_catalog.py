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


# Explicit, uncomplicated numbered listing only. This is deliberately narrower
# than search_request: additional/relative criteria, comparisons, preference
# updates, negation, named properties and other actions cannot enter this path.
_DIRECT_LIST = re.compile(
    r'\s*(?:please\s+)?(?:show me|list|find(?: me)?|give me)\s+(?:the\s+)?'
    r'(?:available\s+)?(?P<beds>\d{1,2}|one|two|three|four|five|six)\s*[- ]?\s*bedrooms?\s+'
    r'(?:houses|homes|properties)\s+(?P<cap>under|below|less than|up to|at most)\s+'
    r'(?:(?:USD\s+)|\$\s*)(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?\s*[kKmM]?)\s+'
    r'(?:as|in)\s+(?:a\s+)?numbered\s+list[.!?]?\s*', re.I)


def reconcile_direct_catalog(reply, *, buyer_message, search_batches, menus,
                             observations, active_search, inbound_id, media_offer,
                             channel, audit=None):
    """Rebuild an undelivered direct listing from ONE exact search result.

    Unlike the general repair, this narrowly scoped path does not require a
    parsed model menu. The actual buyer explicitly requested a numbered list
    with a bedroom count and USD ceiling. A later speculative tool search must
    not overwrite the earlier exact search. Use only a complete exact batch,
    not a union, a prior turn, or a new inferred criterion. If the model's
    order cannot be proven, publish the approved batch order as a NEW menu.
    No operation or preference update is authorized by this presentation.
    Return (reply, menu, selected_search) or None.
    """
    from .commercial_turn import extracted_criteria
    from .conversation_parity import delivered_property_menu
    from .bp_operation_receipts import visible_menu
    from app.modules.sales_agent.response_policy import render_channel_text
    from app.modules.money import parse_amount
    def note(code):
        # Optional diagnostics for the isolated evaluator, no text, prices or IDs.
        if audit is not None and code not in audit.setdefault('reasons',[]):
            audit['reasons'].append(code)

    if (not isinstance(buyer_message, str) or not _DIRECT_LIST.fullmatch(buyer_message)
            or channel not in {'sms','whatsapp'} or media_offer
            or not isinstance(menus,list) or len(menus)>1
            or any(not isinstance(m,dict) or m.get('type')!='property' for m in menus)
            or not observations or any(not isinstance(o,dict)
                or o.get('tool') not in _RECONCILABLE_TOOLS
                or o.get('status')!='executed' or o.get('error_code') is not None
                for o in observations)
            or not isinstance(search_batches,list) or not 1<=len(search_batches)<=50
            or sum(o.get('tool')=='search_properties' for o in observations)!=len(search_batches)):
        note('request_or_tool_evidence')
        return None
    criteria=extracted_criteria(buyer_message)
    if set(criteria)!={'bedrooms','max_price_usd'}:
        note('unsupported_criteria')
        return None
    # The ledger is populated by the actual port, never by model arguments
    # or the model's observations. The latest entry must agree with state.
    if (any(not isinstance(b,dict) or not isinstance(b.get('search'),dict)
            or b['search'].get('source_inbound_message_id')!=inbound_id
            or not isinstance(b.get('rows'),list) for b in search_batches)
            or search_batches[-1]['search']!=active_search):
        note('ledger_mismatch')
        return None
    strict_cap=_DIRECT_LIST.fullmatch(buyer_message)['cap'].casefold() in {'under','below','less than'}
    for batch in reversed(search_batches):
        search=batch['search']; rows=batch['rows']; actual=search.get('criteria')
        if not isinstance(actual,dict) or search.get('scope')!='temporary':
            note('search_scope_or_criteria')
            continue
        # Recognize equivalent exact bounds, not model-invented filters.
        normalized=dict(actual)
        beds=criteria['bedrooms']; cap=criteria['max_price_usd']
        if normalized.get('bedrooms_any')==[beds]:
            normalized.pop('bedrooms_any'); normalized.setdefault('bedrooms',beds)
        if (normalized.get('bedrooms_min')==normalized.get('bedrooms_max')==beds):
            normalized.pop('bedrooms_min'); normalized.pop('bedrooms_max')
            normalized.setdefault('bedrooms',beds)
        if normalized.get('bedrooms')==beds:
            for key in ('bedrooms_min','bedrooms_max'):
                if normalized.get(key)==beds:normalized.pop(key)
        if strict_cap and normalized.get('relative_price_lt')==cap:
            normalized.pop('relative_price_lt'); normalized.setdefault('max_price_usd',cap)
        if normalized!=criteria:
            note('no_exact_criteria')
            continue
        if search.get('match_count')!=len(rows) or not 2<=len(rows)<=9:
            note('incomplete_or_single_result')
            continue
        # Only a complete returned list with known available inventory. Do
        # not use an earlier broad/incomplete search to claim availability.
        if any(not isinstance(row,dict) or not row.get('reference')
               or row.get('availability_verified') is not True
               or (row.get('kind')=='property_type' and
                   (type(row.get('available_units')) is not int or row['available_units']<=0))
               for row in rows):
            note('unverified_inventory')
            continue
        try:
            if any(row.get('bedrooms')!=criteria['bedrooms'] or row.get('currency')!='USD'
                   or parse_amount(row.get('price'))>criteria['max_price_usd']
                   or (parse_amount(row.get('price'))==criteria['max_price_usd'] and
                       strict_cap)
                   for row in rows):
                note('row_filter_conflict')
                continue
            refs=[row['reference'] for row in rows]
            if len(set(refs))!=len(refs):
                note('duplicate_reference')
                continue
            # Re-evaluate on channel-normalized text, not pre-render Markdown.
            rendered=render_channel_text(reply,channel)
            original=delivered_property_menu(rendered,rows)
            if original and set(o['unit_id'] for o in original['options'])==set(refs):
                proposed=original; source=rendered
            else:
                # No previously delivered choice exists for this turn. The
                # new list uses exact catalog labels and the actual batch order.
                from .conversation_parity import display_name
                source='\n'.join(f'{i}. {display_name(row)}' for i,row in enumerate(rows,1))
                proposed=delivered_property_menu(source,rows)
            if not proposed or not visible_menu(source,proposed):
                note('menu_unbound')
                continue
            # Reuse original fail-closed renderer and explicit filter checks.
            repaired=reconcile_numbered_catalog(source,buyer_message=buyer_message,
                search_rows=rows,menus=[proposed],observations=observations,
                active_search=search,inbound_id=inbound_id,media_offer=media_offer,channel=channel)
            if repaired:
                note('canonical_rendered')
                return (*repaired,search)
            note('renderer_rejected')
        except (TypeError,ValueError,KeyError,OverflowError):
            note('invalid_catalog_row')
            continue
    return None
