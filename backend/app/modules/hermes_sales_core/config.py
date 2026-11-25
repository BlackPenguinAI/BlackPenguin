"""Frozen demo-compatible SDK defaults; global staff configuration arrives in P5."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os

PROMPT_PATH = Path(__file__).parent / "prompts" / "global_en_v1.txt"


@dataclass(frozen=True)
class HermesSettings:
    api_key: str = field(repr=False)
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"
    max_iterations: int = 12
    prompt: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required for live SDK invocation")
        if not self.model.strip():
            raise ValueError("A model is required")
        if self.base_url != "https://openrouter.ai/api/v1":
            raise ValueError("P01 only permits the demo's fixed OpenRouter endpoint")
        if not 1 <= self.max_iterations <= 12:
            raise ValueError("max_iterations outside P01 safety cap (1..12)")

    @property
    def effective_prompt(self) -> str:
        return self.prompt or PROMPT_PATH.read_text(encoding="utf-8")

    @classmethod
    def from_environment(cls) -> "HermesSettings":
        return cls(api_key=os.environ.get("OPENROUTER_API_KEY", ""),
                   model=os.environ.get("MODEL_NAME", "openai/gpt-4o-mini"))
