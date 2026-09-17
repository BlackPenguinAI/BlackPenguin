"""Stable, user-facing Project location normalization."""

from __future__ import annotations

import ast
import json
from typing import Any


def _decode_legacy(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    for decoder in (json.loads, ast.literal_eval):
        try:
            parsed = decoder(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (list, dict)):
            return parsed
    # A truncated/invalid serialized structure is not an address.
    return None


def normalize_project_locations(value: Any, fallback: str | None = None) -> list[dict[str, str]]:
    """Return unique ``label/address`` pairs without leaking serialized data."""

    decoded = _decode_legacy(value)
    candidates = decoded if isinstance(decoded, list) else [decoded]
    locations: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        label = "Primary location" if index == 0 else f"Location {index + 1}"
        address: Any = candidate
        if isinstance(candidate, dict):
            label = candidate.get("label") or candidate.get("name") or label
            address = candidate.get("address") or candidate.get("exact_address") or candidate.get("value")
        if not isinstance(address, str) or not address.strip():
            continue
        address = address.strip()
        if address.startswith(("[", "{")):
            continue
        key = address.casefold()
        if key in seen:
            continue
        seen.add(key)
        locations.append({"label": str(label).strip()[:180], "address": address[:500]})

    decoded_fallback = _decode_legacy(fallback)
    if not locations and isinstance(decoded_fallback, str) and decoded_fallback.strip():
        locations.append({"label": "Primary location", "address": decoded_fallback.strip()[:500]})
    return locations


def locations_for_project(project: Any) -> list[dict[str, str]]:
    profile = getattr(project, "profile", None)
    data = getattr(profile, "profile_data", None) or {}
    return normalize_project_locations(data.get("exact_address"), getattr(project, "address", None))


def resolve_visit_location(project: Any, selected: Any = None) -> dict[str, str] | None:
    """Resolve an address by index, label or address; auto-select only when unambiguous."""

    locations = locations_for_project(project)
    if len(locations) == 1 and not selected:
        return locations[0]
    if isinstance(selected, dict):
        selected = selected.get("address") or selected.get("label")
    needle = str(selected or "").strip().casefold()
    if needle.isdigit() and 1 <= int(needle) <= len(locations):
        return locations[int(needle) - 1]
    if needle:
        for location in locations:
            if needle in {location["label"].casefold(), location["address"].casefold()}:
                return location
    return None
