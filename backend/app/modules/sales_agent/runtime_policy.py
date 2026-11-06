"""Published staff policy for scoped disabled, shadow and active execution."""
from typing import Literal
from pydantic import Field, model_validator
from uuid import UUID
from .understanding_contract import StrictModel


class RuntimePolicy(StrictModel):
    mode: Literal['disabled','shadow','active'] = 'disabled'
    company_ids: list[str] = Field(default_factory=list, max_length=100)
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    lead_ids: list[str] = Field(default_factory=list, max_length=100)
    max_steps: int = Field(default=8, ge=1, le=30, strict=True)
    max_seconds: float = Field(default=5, gt=0, le=30, strict=True)
    understanding_guidance: str = Field(default='', max_length=16000)
    composition_style: Literal['concise','detailed'] = 'concise'

    @model_validator(mode='after')
    def scoped_activation(self):
        if self.mode in {'shadow','active'} and (not self.company_ids or not self.project_ids):
            raise ValueError('Shadow/active mode requires company and project allowlists.')
        for values in (self.company_ids,self.project_ids,self.lead_ids):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate scope IDs.')
            for value in values:
                if str(UUID(value)) != value:
                    raise ValueError('Use canonical UUID scope IDs, not wildcards.')
        return self

    def selects(self, scope):
        return (self.mode in {'shadow','active'} and bool(self.company_ids) and bool(self.project_ids)
                and scope.company_id in self.company_ids and scope.project_id in self.project_ids
                and (not self.lead_ids or scope.lead_id in self.lead_ids))
