"""Lossless monetary parsing. Ambiguous human input must be clarified, not guessed."""
from decimal import Decimal, InvalidOperation
import re


def parse_amount(value, *, locale=None) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Enter a monetary amount, not a boolean or empty value.")
    text = str(value).strip()
    if isinstance(value, str):
        text = text.replace("\u00a0", " ").replace("\u202f", " ")
        if " " in text:
            if not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?", text):
                raise ValueError("Use an ungrouped amount such as 30000.00.")
            text = text.replace(" ", "")
        if "," in text and "." in text:
            decimal, group = (",", ".") if text.rfind(",") > text.rfind(".") else (".", ",")
            if not re.fullmatch(r"\d{1,3}(?:" + re.escape(group) + r"\d{3})+" + re.escape(decimal) + r"\d{1,2}", text):
                raise ValueError("Use a consistent monetary separator format.")
            text = text.replace(group, "").replace(decimal, ".")
        elif "," in text or "." in text:
            separator = "," if "," in text else "."
            if re.fullmatch(r"\d{1,3}(?:" + re.escape(separator) + r"\d{3})+", text):
                expected_group = "," if locale == "en_US" else "." if locale == "es_ES" else None
                if expected_group != separator:
                    raise ValueError("This amount is ambiguous. Use 30000 for thirty thousand or 30.00 for thirty.")
                text = text.replace(separator, "")
            else:
                text = text.replace(",", ".")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
            raise ValueError("Enter a non-negative amount with at most two decimal places, without a currency symbol.")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid monetary amount.") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("99999999999999.99") or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Enter a finite, non-negative amount with at most two decimal places.")
    return amount


def format_amount(value) -> str:
    amount = parse_amount(value)
    return f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
