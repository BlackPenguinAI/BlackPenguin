"""Validate price claims against this turn's approved, tenant-scoped facts."""
from decimal import Decimal
import re

from app.modules.money import format_amount, parse_amount

CODES = r"USD|MXN|PEN|EUR|COP|BRL|CLP|ARS|CAD|GBP|DOLLAR|PESO"
NUMBER = r"-?\d+(?:[.,]\d+)*(?:[ \u00a0\u202f]\d{3})*(?:\s*(?:[kKmM]|million|thousand))?"
JOIN = r"\s*(?:[–—-]|to\b|through\b|and\b|hasta\b|a\b|y\b)\s*"
CURRENCY = rf"(?:{CODES}|US\$|\$|€|£)"
CLAIM = re.compile(rf"(?<!\w)(?:(?P<before>{CURRENCY})\s*(?P<a>{NUMBER})(?:{JOIN}(?P<upper_a>{NUMBER})(?:\s*(?P<upper_currency>{CURRENCY}))?)?|(?P<b>{NUMBER})(?:{JOIN}(?P<upper_b>{NUMBER}))?\s*(?P<after>{CURRENCY})(?:{JOIN}(?P<upper_c>{NUMBER})(?:\s*(?P<tail_currency>{CURRENCY}))?)?)(?!\w)", re.I)

# A conjunction does not make every quantity after a price another price.
# These are semantic units, not Project/PDF-specific names. An explicitly
# currency-labelled endpoint remains monetary even when a unit follows it.
NON_MONETARY_UNIT = re.compile(
    r"\s*(?:full\s+|half\s+)?(?:bedrooms?|bathrooms?|beds?|baths?|rooms?|"
    r"dormitorios?|habitaciones?|rec[aá]maras?|ba[nñ]os?|ambientes?|"
    r"units?|homes?|apartments?|unidades?|departamentos?|casas?|"
    r"parking\s+(?:spaces?|slots?)|garages?|plazas?|cajones?|"
    r"floors?|levels?|storeys?|stories|pisos?|niveles?|"
    r"days?|weeks?|months?|years?|hours?|minutes?|d[ií]as?|semanas?|meses?|a[nñ]os?|horas?|minutos?|"
    r"square\s+(?:met(?:er|re)s?|feet|foot)|sq\.?\s*(?:ft|m)|m[²2]|ft[²2]|"
    r"metros?\s+cuadrados?|acres?|hectares?|hect[aá]reas?|percent|por\s+ciento)\b|\s*%", re.I,
)


def _currency_code(raw):
    code = (raw or "").upper()
    return {"US$": "USD", "€": "EUR", "£": "GBP"}.get(code, code)


def _range_bounds(claim, text):
    bounds = []
    for name, currency in (("upper_a", "upper_currency"), ("upper_b", "after"), ("upper_c", "tail_currency")):
        raw = claim.group(name)
        if raw is None:
            continue
        explicit_currency = claim.group(currency)
        if not explicit_currency and NON_MONETARY_UNIT.match(text, claim.end(name)):
            continue
        bounds.append((raw, _currency_code(explicit_currency)))
    return bounds


def _normalize_currency_words(text):
    # Generic dollars/pesos are deliberately not assigned a country. The
    # permitted catalog currencies must disambiguate them, just like '$'.
    aliases = [
        (r"(?:US|U\.S\.|American)\s+dollars?|d[oó]lares?\s+estadounidenses?", "USD"),
        (r"Canadian\s+dollars?|d[oó]lares?\s+canadienses?", "CAD"),
        (r"Mexican\s+pesos?|pesos?\s+mexicanos?", "MXN"),
        (r"dollars?|d[oó]lares?", "DOLLAR"), (r"pesos?", "PESO"),
        (r"euros?", "EUR"), (r"soles|sol\s+peruano", "PEN"),
        (r"pounds?|libras?", "GBP"),
    ]
    for pattern, code in aliases:
        text = re.sub(r"\b(?:" + pattern + r")\b", code, text, flags=re.I)
    return text


def _currency_matches(code, currency):
    families = {"$": {"USD", "MXN", "CAD", "ARS", "CLP", "COP"},
                "DOLLAR": {"USD", "CAD"}, "PESO": {"MXN", "ARS", "CLP", "COP"}}
    return code == currency or currency in families.get(code, set())


def _prices(commercial):
    # Structured records supersede the profile-wide minimum. Never let an old
    # free-text profile value add an alternative price to the permitted set.
    rows = list(commercial.get("property_types") or [])
    if not rows or commercial.get("inventory_source") == "individual_units":
        rows.extend(commercial.get("inventory") or [])
    result = []
    for row in rows:
        currency = str(row.get("currency") or "").upper()
        for field in ("starting_price", "maximum_price", "price"):
            if row.get(field) is None or not currency:
                continue
            try:
                name = row.get("unit_code") or row.get("property_type") or "Project"
                if field == "maximum_price":
                    name += " (maximum price)"
                result.append((name, parse_amount(row[field]), currency, row.get("id")))
            except ValueError:
                continue
    if not rows:
        facts = commercial.get("confirmed_project_facts") or {}
        if facts.get("starting_price") is not None and facts.get("currency"):
            try:
                result.append((facts.get("project_name") or "Project", parse_amount(facts["starting_price"]), str(facts["currency"]).upper(), None))
            except ValueError:
                pass
    return result


def validate_monetary_reply(reply, commercial, *, lead_profile=None):
    prices = _prices(commercial)
    normalized = _normalize_currency_words(reply or "")
    claims = list(CLAIM.finditer(normalized))
    invalid = []
    for claim in claims:
        code = _currency_code(claim.group("before") or claim.group("after"))
        raw = claim.group("a") or claim.group("b")
        bounds = _range_bounds(claim, normalized)
        range_codes = [currency for _, currency in bounds if currency]
        try:
            # Customer-facing machine output has an explicit English display
            # contract; onboarding input is parsed separately without guessing.
            amount = parse_amount(raw, locale="en_US")
            amounts = [amount, *[parse_amount(value, locale="en_US") for value, _ in bounds]]
            if any(right < left for left, right in zip(amounts, amounts[1:])):
                invalid.append(claim.group()); continue
        except ValueError:
            invalid.append(claim.group()); continue
        # Acknowledging an explicit lead budget is not a Project price claim.
        # Exempt only amounts actually stored in the lead's verified facts.
        prefix = normalized[:claim.start()].rsplit("\n", 1)[-1].rsplit(". ", 1)[-1]
        if re.match(r"\s*(?:your|you mentioned(?: a)?)\s+budget\b", prefix, re.I):
            facts = (lead_profile or {}).get("facts") or {}
            budget = (facts.get("budget") or {}).get("value") or {}
            values = [budget.get(key) for key in ("minimum", "maximum")] if isinstance(budget, dict) else []
            values += [(facts.get(key) or {}).get("value") for key in ("budget_minimum", "budget_maximum")]
            currency = str((facts.get("budget_currency") or {}).get("value") or (budget.get("currency") if isinstance(budget, dict) else "") or "").upper()
            if currency and all(_currency_matches(c, currency) for c in [code, *range_codes]):
                known = [Decimal(str(value)) for value in values if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)]
                if all(value in known for value in amounts):
                    continue
        matching = [(v, c) for _, v, c, _ in prices if _currency_matches(code, c)]
        # If the sentence names a particular record, a price of a different
        # record is not enough evidence for this claim.
        named = [(prefix.casefold().rfind(name.casefold()), rid) for name, _, _, rid in prices if name.casefold() in prefix.casefold()]
        if named:
            record_id = max(named, key=lambda pair: pair[0])[1]
            matching = [(v, c) for _, v, c, rid in prices if rid == record_id and _currency_matches(code, c)]
        if range_codes:
            matching = [(v,c) for v,c in matching if all(_currency_matches(rc,c) for rc in range_codes)]
        if (code in {"$", "DOLLAR", "PESO"} and len({c for _, c in matching}) != 1) or not all(any(v == value for v, _ in matching) for value in amounts):
            invalid.append(claim.group())
    evidence = {
        "checked": bool(claims), "replaced": bool(invalid), "rejected_claims": invalid,
        "original_reply": reply if invalid else None,
        "approved_revision": commercial.get("approved_revision"),
        "sources": [{"id": rid, "name": name, "amount": str(value), "currency": currency} for name, value, currency, rid in prices],
    }
    if not invalid:
        return reply, evidence
    # Do not guess which record a wrong amount referred to or mutate the
    # approved value. Quote the exact approved records instead, without pausing.
    seen = set(); lines = []
    for name, value, currency, _ in prices:
        key = (name, value, currency)
        if key not in seen:
            seen.add(key); lines.append(f"• {name}: {format_amount(value)} {currency}")
    safe = "Here are the prices I can verify from the approved Project information:\n\n" + "\n".join(lines) if lines else "I don't have a confirmed price to quote yet. I can help with the other approved Project information."
    return safe, evidence
