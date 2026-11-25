"""Portable Hermes Sales Core, extracted from testing-hermes-agent v13.3.3.

This package is deliberately NOT wired into the live BlackPenguin agent.
It has no SQLAlchemy/Turso, FastAPI, messaging or booking provider imports.
"""
from .contracts import TurnScope, TurnRequest, TurnResult, ToolPort
from .config import HermesSettings
from .runtime import HermesSalesRuntime

__all__ = ["TurnScope", "TurnRequest", "TurnResult", "ToolPort", "HermesSettings", "HermesSalesRuntime"]
