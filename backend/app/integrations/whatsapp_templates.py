"""Black Penguin's production contract for the first WhatsApp contact."""

from __future__ import annotations

import re


INITIAL_TEMPLATE_LANGUAGE = "en_US"
INITIAL_TEMPLATE_PARAMETER_INDEXES = {1, 2}
_PARAMETER_PATTERN = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def template_parameter_indexes(content: str | None) -> set[int]:
    return {int(value) for value in _PARAMETER_PATTERN.findall(content or "")}


def validate_initial_template(*, language: str | None, content: str | None) -> None:
    """Validate the approved template shape expected by the live lead workflow."""
    if (language or "").strip() != INITIAL_TEMPLATE_LANGUAGE:
        raise ValueError("The initial WhatsApp template must use English (en_US).")
    if not (content or "").strip():
        raise ValueError("The approved WhatsApp template body could not be loaded from Telnyx.")
    indexes = template_parameter_indexes(content)
    if indexes != INITIAL_TEMPLATE_PARAMETER_INDEXES:
        raise ValueError(
            "The initial WhatsApp template must contain exactly {{1}} for the lead first name "
            "and {{2}} for the Project name."
        )


def initial_template_parameters(*, lead_name: str | None, project_name: str | None) -> list[str]:
    first_name = (lead_name or "").strip().split(maxsplit=1)[0] if (lead_name or "").strip() else "there"
    project = (project_name or "").strip()
    if not project:
        raise ValueError("A Project name is required for the initial WhatsApp message.")
    return [first_name[:120], project[:240]]


def render_initial_template(content: str, parameters: list[str]) -> str:
    if len(parameters) != 2:
        raise ValueError("The initial WhatsApp template requires two parameters.")
    rendered = content
    for index, value in enumerate(parameters, start=1):
        rendered = re.sub(r"\{\{\s*" + str(index) + r"\s*\}\}", value, rendered)
    if _PARAMETER_PATTERN.search(rendered):
        raise ValueError("The initial WhatsApp template contains unresolved parameters.")
    return rendered.strip()
