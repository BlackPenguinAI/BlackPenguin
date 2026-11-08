"""Platform-owned staging switch, independent from editable Sales prompts."""
from uuid import UUID
from app.core.config import settings


def selected(scope):
    if not settings.SALES_NEXT_FLOW_ENABLED:
        return False
    values=[value.strip() for value in settings.SALES_NEXT_FLOW_PROJECT_IDS.split(',') if value.strip()]
    try:
        if not values or any(str(UUID(value))!=value for value in values):
            return False
    except (ValueError,TypeError):
        return False
    return scope.project_id in values
