from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.projects.models import Project


def sync_project_country(db: Session, *, company_id: str, country_code: str) -> None:
    """Keep existing Projects aligned with their Company's operating country."""
    for project in db.query(Project).filter(Project.company_id == company_id).all():
        project.country = country_code
        if not project.profile:
            continue
        data = dict(project.profile.profile_data or {})
        states = dict(project.profile.field_states or {})
        data["country"] = country_code
        states["country"] = {"status": "confirmed", "applicable": True}
        project.profile.profile_data = data
        project.profile.field_states = states
        flag_modified(project.profile, "profile_data")
        flag_modified(project.profile, "field_states")

