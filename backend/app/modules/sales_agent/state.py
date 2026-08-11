from typing import Any, TypedDict


class SalesAgentState(TypedDict, total=False):
    event_id: str
    mode: str
    conversation_id: str
    company_id: str
    project_id: str
    campaign_id: str | None
    lead_id: str
    inbound_text: str
    channel: str
    company_context: dict[str, Any]
    project_context: dict[str, Any]
    inventory_context: list[dict[str, Any]]
    lead_context: dict[str, Any]
    prompt_snapshot: dict[str, Any]
    prompt_configuration_id: str | None
    model: str
    intent: str | None
    extracted_facts: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    proposed_reply: str | None
    requires_human: bool
    policy_violations: list[str]
    error_code: str | None
