"""Execution limits for the current workflow; historical rollout fields are inert."""
from typing import Literal
from pydantic import Field, model_validator
from .understanding_contract import StrictModel


class RuntimePolicy(StrictModel):
    mode: Literal['disabled','shadow','active'] = 'active'
    scope: Literal['cohort','global'] = 'global'
    company_ids: list[str] = Field(default_factory=list, max_length=100)
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    lead_ids: list[str] = Field(default_factory=list, max_length=100)
    max_steps: int = Field(default=8, ge=1, le=30, strict=True)
    max_seconds: float = Field(default=5, gt=0, le=30, strict=True)
    max_rounds: int = Field(default=3,ge=1,le=6,strict=True)
    max_read_units: int = Field(default=12,ge=1,le=60,strict=True)
    understanding_guidance: str = Field(default='', max_length=16000)
    composition_style: Literal['concise','detailed'] = 'concise'

    @model_validator(mode='before')
    @classmethod
    def current_workflow(cls, value):
        if isinstance(value, dict):
            value = {**value, 'mode': 'active', 'scope': 'global',
                     'company_ids': [], 'project_ids': [], 'lead_ids': []}
        return value

    def selects(self, scope):
        return True
