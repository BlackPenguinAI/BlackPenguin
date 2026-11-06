"""Lossless, question-bound transport for explicit onboarding selections."""
from pydantic import BaseModel, Field, StrictStr, model_validator

from .onboarding_selection import normalize_selection


class StructuredChatMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    in_reply_to_message_id: str | None = None
    selected_values: list[StrictStr] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def bind_selection(self):
        if self.selected_values is not None:
            if not self.in_reply_to_message_id:
                raise ValueError('A selection must reference its onboarding question.')
            if any(not value.strip() for value in self.selected_values):
                raise ValueError('Each selected option must contain text.')
            # The visible history must describe the same values as the payload.
            text = '; '.join(self.selected_values).strip()
            if not text or len(text) > 20000:
                raise ValueError('Enter a non-empty selection of at most 20000 characters.')
            self.message = text
        return self


def question_selection(field, question, values):
    from .onboarding_questions import QUESTION_CATALOG
    if (question.get('input_type') != 'multi_select'
            or QUESTION_CATALOG.get(field, {}).get('input_type') != 'multi_select'):
        raise ValueError('This question does not accept multiple selections.')
    choices = list(question.get('options') or []) + list(question.get('selected_values') or [])
    result = normalize_selection(field, values, choices)
    if not result:
        raise ValueError('Select at least one value.')
    if not question.get('allow_custom', True) and any(value not in choices for value in result):
        raise ValueError('Choose one of the available options.')
    return result
