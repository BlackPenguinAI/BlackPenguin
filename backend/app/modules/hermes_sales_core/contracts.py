"""Boundary contracts. Transport/persistence are owned by BlackPenguin, not Hermes."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class TurnScope:
    company_id: str
    project_id: str
    conversation_id: str
    lead_id: str

    def __post_init__(self) -> None:
        for field_name in ("company_id", "project_id", "conversation_id", "lead_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing authorized {field_name}")


@dataclass(frozen=True)
class TurnRequest:
    scope: TurnScope
    message: str
    history: list[dict[str, Any]] = field(default_factory=list)
    verified_context: dict[str, Any] = field(default_factory=dict)
    # Never accepted as proof of user authorization. Only the gateway may approve effects.
    channel: str = "simulation"

    def __post_init__(self) -> None:
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("A nonempty buyer message is required")
        if self.channel not in {"simulation", "sms", "whatsapp"}:
            raise ValueError("Unsupported channel")
        if not isinstance(self.verified_context, dict) or not isinstance(self.history, list):
            raise TypeError("History and context must be JSON-compatible containers")


@dataclass(frozen=True)
class TurnResult:
    reply: str
    history: list[dict[str, Any]]
    tool_observations: list[dict[str, Any]]
    engine_version: str = "hermes-sales-core/0.1-p01"


class ToolPort(Protocol):
    """Business tool gateway, scoped by server-authorized IDs.

    P01 supplies ONLY offline fixture ports. No production implementation exists.
    Every future implementation MUST verify the four IDs independently.
    """
    def invoke(self, name: str, arguments: Mapping[str, Any], scope: TurnScope) -> dict[str, Any]: ...
