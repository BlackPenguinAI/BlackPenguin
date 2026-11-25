"""Catalog-verified, buyer-visible property choices (Hermes v13.3.2).

This is deterministic reference/presentation logic, not another LLM agent.
Ordinal choices bind to the LAST actually delivered menu, never the permanent
shortlist. Choosing a property for details never consents to a visit.
"""
from __future__ import annotations

import re
from typing import Any

_CODE = re.compile(r'(?<![A-Z0-9])H[- ]?(\d{3})(?![A-Z0-9])', re.I)
_NUMBER = re.compile(r'\b(?:option|choice|number|no\.?|#)\s*#?\s*([1-9])\b', re.I)
_ORDINALS = (
    (1, re.compile(r'\b(?:first|1st)(?:\s+(?:one|house|home|property|option))?\b', re.I)),
    (2, re.compile(r'\b(?:second|2nd)(?:\s+(?:one|house|home|property|option))?\b', re.I)),
    (3, re.compile(r'\b(?:third|3rd)(?:\s+(?:one|house|home|property|option))?\b', re.I)),
    (4, re.compile(r'\b(?:fourth|4th)(?:\s+(?:one|house|home|property|option))?\b', re.I)),
)
_PRICE = re.compile(r'\$\s*(\d{2,7}(?:,\d{3})*(?:\.\d+)?)\s*([km])?\b', re.I)
_SEARCH_MORE = re.compile(
    r'\b(?:other|more|different|another)\s+(?:options?|houses?|homes?|properties)\b|'
    r'\b(?:search|find|show me)\s+(?:other|more|different)\s+(?:houses?|homes?|properties)\b', re.I)
_VISIT = re.compile(r'\b(?:visit|tour|book|schedule|appointment|reschedule|cancel|confirm)\b', re.I)
_MEDIA = re.compile(r'\b(?:gallery|photos?|pictures?|images?|pdf|brochure|floor.?plan)\b', re.I)
_BUDGET = re.compile(r'\b(?:budget|spend|maximum|minimum|under|up to|afford|price range|cheaper|expensive)\b', re.I)
_BAD_TEXT = re.compile(r'\b(?:system (?:issue|error)|validation error|tool error|internal error|'
                       r'found\s+\d+\s+matching|which\s+(?:one|house)\s+would you|'
                       r'retrieving properties|search again)\b', re.I)


def _codes(text: str) -> list[str]:
    return list(dict.fromkeys('H-' + match.group(1) for match in _CODE.finditer(text or '')))


def option_number(message: str, *, has_visible_options: bool = False) -> int | None:
    text = str(message or '')
    match = _NUMBER.search(text) or re.search(r'(?<!\w)#\s*([1-9])\b', text)
    if match is None and has_visible_options:
        match = re.fullmatch(r'\s*([1-9])[.!]?\s*', text)
    if match:
        return int(match.group(1))
    for number, pattern in _ORDINALS:
        if pattern.search(text):
            return number
    if re.search(r'\b(?:the\s+)?latter\b', text, re.I):
        return -1
    if re.search(r'\b(?:the\s+)?former\b', text, re.I):
        return 1
    return None


def is_option_selection(message: str, *, has_visible_options: bool = False) -> bool:
    text = str(message or '')
    # An explicit request to schedule/photo/book is not a request for details.
    if _VISIT.search(text) or _MEDIA.search(text):
        return False
    if _SEARCH_MORE.search(text) and not _NUMBER.search(text):
        return False
    if option_number(text, has_visible_options=has_visible_options) is not None:
        return True
    if _CODE.search(text) and re.search(
        r'\b(?:choose|pick|prefer|interested in|details? (?:about|of|on)|'
        r'tell me about|look at|explore)\b', text, re.I):
        return True
    if _PRICE.search(text) and not _BUDGET.search(text) and re.search(
        r'\b(?:the|that|this|one|house|home|property|prefer|interested|choose|pick)\b',
        text, re.I):
        return True
    return False


def _amount(text: str) -> int | None:
    match = _PRICE.search(text or '')
    if not match:
        return None
    value = float(match.group(1).replace(',', ''))
    return round(value * {'k': 1000, 'm': 1000000}.get((match.group(2) or '').lower(), 1))


def resolve_selection(state: dict, message: str) -> dict[str, Any] | None:
    """Reference exactly the last delivered menu, even if the shortlist differs."""
    snap = state.get('last_presented_property_options') or {}
    options = snap.get('options') or []
    if not is_option_selection(message, has_visible_options=bool(options)):
        return None
    codes = _codes(message)
    if len(codes) > 1:
        return dict(unit_id=None, ambiguous=True, reason='multiple_explicit_options', candidates=codes)
    if len(codes) == 1:
        matches = [item for item in options if item['unit_id'] == codes[0]]
        # An explicit code outside the shown menu is handled by the regular
        # named-unit resolver (not silently assigned an ordinal).
        if not matches:
            return None
    else:
        index = option_number(message, has_visible_options=bool(options))
        if index == -1:
            index = len(options) if len(options) == 2 else None
        if index is not None:
            matches = [item for item in options if item['display_number'] == index]
        else:
            price = _amount(message)
            matches = [item for item in options if item.get('price_usd') == price] if price else []
    if len(matches) == 1:
        chosen = matches[0]
        return dict(unit_id=chosen['unit_id'], ambiguous=False, reason='presented_option',
                    display_number=chosen['display_number'],
                    source_reply_message_id=snap.get('source_reply_message_id'))
    return dict(unit_id=None, ambiguous=True, reason='unknown_or_ambiguous_option',
                candidates=[item['unit_id'] for item in options])


def _money(value: int | float, compact: bool = False) -> str:
    value = int(value)
    return f'${value // 1000}k' if compact and value % 1000 == 0 else f'${value:,}'


def _visible(matches: list[dict]) -> list[dict]:
    return [unit for unit in matches[:3] if unit.get('unit_id')]


def _line(unit: dict, ordinal: int | None) -> str:
    label = f'{unit["unit_id"]} ({unit["bedrooms"]} beds, {_money(unit["price_usd"], True)})'
    return f'{ordinal}. {label}' if ordinal is not None else label


def render_matches(matches: list[dict]) -> str:
    """Always return real newline-separated SMS options; no Markdown needed."""
    visible = _visible(matches)
    if not visible:
        return 'No houses match those criteria. Would you like to adjust a preference?'
    sizes = {unit.get('bedrooms') for unit in visible}
    descriptor = f'{next(iter(sizes))}-bedroom ' if len(sizes) == 1 else ''
    if len(visible) == 1:
        return (f'I found a {descriptor}house matching your search:\n\n'
                f'{_line(visible[0], None)}\n\n'
                'Would you like more details, or explore other options?')
    parts = [f'I found {len(matches)} {descriptor}houses:', '']
    parts.extend(_line(unit, i) for i, unit in enumerate(visible, 1))
    if len(matches) > len(visible):
        parts.extend(['', f'{len(matches) - len(visible)} more matching houses are available.'])
    parts.extend(['', 'Which would you like to explore? I can also look for homes with different features.'])
    return '\n'.join(parts)


def needs_listing_repair(reply: str, matches: list[dict]) -> bool:
    visible = _visible(matches)
    if not visible:
        return False
    text = str(reply or '')
    if _BAD_TEXT.search(text) or _codes(text) != [item['unit_id'] for item in visible]:
        return True
    lines = [line.strip() for line in text.splitlines()
             if re.match(r'^\s*(?:[1-9]\.\s+)?H-\d{3}\b', line, re.I)]
    expected = [_line(item, i if len(visible) > 1 else None)
                for i, item in enumerate(visible, 1)]
    return lines != expected or len(text.splitlines()) < 4


def delivered_snapshot(matches: list[dict], reply: str, *,
                       search_revision: int | None = None,
                       reply_message_id: str | None = None) -> dict | None:
    """Persist ONLY choices actually sent, in their visible presentation order."""
    visible = _visible(matches)
    if not visible:
        return None
    ordered = []
    for unit in visible:
        hit = re.search(r'(?<![\w])' + re.escape(unit['unit_id']) + r'\b', reply, re.I)
        if not hit:
            return None
        ordered.append((hit.start(), unit))
    ordered.sort(key=lambda pair: pair[0])
    return {'search_revision': search_revision,
            'source_reply_message_id': reply_message_id,
            'options': [dict(display_number=i, unit_id=unit['unit_id'],
                             commercial_name=unit.get('commercial_name'),
                             price_usd=unit.get('price_usd'))
                        for i, (_, unit) in enumerate(ordered, 1)]}


def selected_property_reply(unit: dict) -> str:
    features = unit.get('confirmed_features') or {}
    facts = [f'{unit["bedrooms"]} bedrooms', f'{unit["bathrooms"]} bathrooms',
             f'{unit["area_sqm"]} sq m of built area']
    if features.get('kitchen_layout'):
        facts.append(f'{features["kitchen_layout"]} kitchen')
    parking = features.get('parking_spaces')
    if parking is not None:
        facts.append(f'{parking} parking space' + ('s' if int(parking) != 1 else ''))
    available = unit.get('available_from_date')
    available_text = f'Available from {available}' if available and available != 'Immediate' else 'Ready now'
    return (f'Great choice to explore: {unit["commercial_name"]} ({unit["unit_id"]}).\n\n'
            f'{", ".join(facts)}.\n'
            f'Price: {_money(unit["price_usd"])} | {available_text}.\n\n'
            'Would you like photos, the property PDF, or to plan a visit?')


def needs_selection_repair(reply: str, unit: dict) -> bool:
    text = str(reply or '')
    named = _codes(text)
    if _BAD_TEXT.search(text) or (named and any(code != unit['unit_id'] for code in named)):
        return True
    # A correct unit code with the wrong listing price or bedroom count is
    # still misinformation. Rebuild the answer from the published unit data.
    price_mentions = [_amount(hit.group(0)) for hit in _PRICE.finditer(text)]
    if price_mentions and any(amount != int(unit['price_usd']) for amount in price_mentions):
        return True
    bedroom_mentions = [int(hit.group(1)) for hit in re.finditer(
        r'\b([1-9])\s*(?:bedrooms?|beds?)\b', text, re.I)]
    if bedroom_mentions and any(count != int(unit['bedrooms']) for count in bedroom_mentions):
        return True
    return unit['unit_id'] not in named and unit['commercial_name'].lower() not in text.lower()
