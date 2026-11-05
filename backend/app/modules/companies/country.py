from sqlalchemy.orm import Session


def sync_project_country(db: Session, *, company_id: str, country_code: str) -> None:
    """Compatibility hook: Company country is a suggestion, never a Project relocation.

    The editor reads the current Company country for missing Project locations.
    No approved country, draft, timezone or appointment is rewritten here.
    """
    return None
