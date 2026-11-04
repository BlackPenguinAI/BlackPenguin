"""Validate price claims against this turn's approved, tenant-scoped facts."""
from decimal import Decimal
import re

from app.modules.money import format_amount, parse_amount

CODES = r"USD|MXN|PEN|EUR|COP|BRL|CLP|ARS|CAD|GBP|DOLLAR|PESO"
NUMBER = r"-?\d+(?:[.,]\d+)*(?:[ \u00a0\u202f]\d{3})*(?:\s*(?:[kKmM]|million|thousand))?"
JOIN = r"\s*(?:[–—-]|to\b|through\b|and\b|hasta\b|a\b|y\b)\s*"
CURRENCY = rf"(?:{CODES}|US\$|\$|€|£)"
CLAIM = re.compile(rf"(?<!\w)(?:(?P<before>{CURRENCY})\s*(?P<a>{NUMBER})(?:{JOIN}(?P<upper_a>{NUMBER})(?:\s*(?P<upper_currency>{CURRENCY}))?)?|(?P<b>{NUMBER})(?:{JOIN}(?P<upper_b>{NUMBER}))?\s*(?P<after>{CURRENCY}))(?!\w)", re.I)


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
        code = (claim.group("before") or claim.group("after")).upper()
        code = {"US$": "USD", "€": "EUR", "£": "GBP"}.get(code, code)
        raw = claim.group("a") or claim.group("b")
        upper = claim.group("upper_a") or claim.group("upper_b")
        upper_code = (claim.group("upper_currency") or "").upper()
        upper_code = {"US$":"USD", "€":"EUR", "£":"GBP"}.get(upper_code, upper_code)
        try:
            # Customer-facing machine output has an explicit English display
            # contract; onboarding input is parsed separately without guessing.
            amount = parse_amount(raw, locale="en_US")
            upper_amount = parse_amount(upper, locale="en_US") if upper else None
            if upper_amount is not None and upper_amount < amount:
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
            if currency and _currency_matches(code, currency) and (not upper_code or _currency_matches(upper_code, currency)):
                known = [Decimal(str(value)) for value in values if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)]
                if amount in known and (upper_amount is None or upper_amount in known):
                    continue
        matching = [(v, c) for _, v, c, _ in prices if _currency_matches(code, c)]
        # If the sentence names a particular record, a price of a different
        # record is not enough evidence for this claim.
        named = [(prefix.casefold().rfind(name.casefold()), rid) for name, _, _, rid in prices if name.casefold() in prefix.casefold()]
        if named:
            record_id = max(named, key=lambda pair: pair[0])[1]
            matching = [(v, c) for _, v, c, rid in prices if rid == record_id and _currency_matches(code, c)]
        if upper_code:
            matching = [(v,c) for v,c in matching if _currency_matches(upper_code,c)]
        if (code in {"$", "DOLLAR", "PESO"} and len({c for _, c in matching}) != 1) or not any(v == amount for v, _ in matching) or (upper_amount is not None and not any(v == upper_amount for v, _ in matching)):
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
