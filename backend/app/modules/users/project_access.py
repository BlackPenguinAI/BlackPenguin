from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project

from .models import User, UserProjectAccess, UserRole


PROJECT_SCOPES = {"all", "selected"}


def project_ids_for_user(db: Session, user: User) -> list[str]:
    if not user.company_id:
        return []
    if user.role == UserRole.ADMIN or (user.project_access_scope or "all") == "all":
        return [
            row[0] for row in db.query(Project.id).filter(
                Project.company_id == user.company_id, Project.is_active.is_(True),
            ).order_by(Project.name).all()
        ]
    return [
        row[0] for row in db.query(UserProjectAccess.project_id).join(
            Project, Project.id == UserProjectAccess.project_id,
        ).filter(
            UserProjectAccess.user_id == user.id,
            UserProjectAccess.is_active.is_(True),
            Project.company_id == user.company_id,
            Project.is_active.is_(True),
        ).order_by(Project.name).all()
    ]


def can_access_project(db: Session, user: User, project_id: str) -> bool:
    if not user.company_id:
        return False
    project = db.query(Project.id).filter(
        Project.id == project_id, Project.company_id == user.company_id,
    ).first()
    if not project:
        return False
    if user.role == UserRole.ADMIN or (user.project_access_scope or "all") == "all":
        return True
    return db.query(UserProjectAccess.id).filter(
        UserProjectAccess.user_id == user.id,
        UserProjectAccess.project_id == project_id,
        UserProjectAccess.is_active.is_(True),
    ).first() is not None


def require_project_access(db: Session, user: User, project_id: str) -> None:
    if not can_access_project(db, user, project_id):
        raise HTTPException(status_code=404, detail="Project not found or not assigned to this user.")


def sync_user_project_access(
    db: Session,
    *,
    user: User,
    scope: str,
    project_ids: list[str],
    allow_empty_selected: bool = False,
) -> None:
    if scope not in PROJECT_SCOPES:
        raise HTTPException(status_code=422, detail="Project access must be all or selected.")
    if user.role == UserRole.ADMIN:
        scope = "all"
        project_ids = []
    unique_ids = list(dict.fromkeys(project_ids))
    company_projects = db.query(Project).filter(
        Project.company_id == user.company_id, Project.is_active.is_(True),
    ).all()
    project_by_id = {project.id: project for project in company_projects}
    unknown = sorted(set(unique_ids) - set(project_by_id))
    if unknown:
        raise HTTPException(status_code=422, detail="One or more selected Projects are invalid for this Company.")
    if scope == "selected" and not unique_ids and not allow_empty_selected:
        raise HTTPException(status_code=422, detail="Select at least one Project or choose All Projects.")

    user.project_access_scope = scope
    existing_access = {
        item.project_id: item for item in db.query(UserProjectAccess).filter(
            UserProjectAccess.user_id == user.id,
        ).all()
    }
    selected_ids = set(unique_ids) if scope == "selected" else set()
    for project_id, item in existing_access.items():
        item.is_active = project_id in selected_ids
        db.add(item)
    for project_id in selected_ids - set(existing_access):
        db.add(UserProjectAccess(user_id=user.id, project_id=project_id, is_active=True))

    operational_ids = set(project_by_id) if scope == "all" else selected_ids
    responsibility = {
        UserRole.SALES: "sales",
        UserRole.MKT: "marketing",
    }.get(user.role)
    assignments = {
        item.project_id: item for item in db.query(ProjectUserAssignment).filter(
            ProjectUserAssignment.user_id == user.id,
        ).all()
    }
    for project_id, item in assignments.items():
        should_be_active = responsibility is not None and project_id in operational_ids
        item.is_active = should_be_active
        if should_be_active:
            item.responsibility = responsibility
            if item.accepts_new_leads is None:
                item.accepts_new_leads = True
        elif item.responsibility == "sales":
            item.accepts_new_leads = False
        db.add(item)
    if responsibility:
        for project_id in operational_ids - set(assignments):
            db.add(ProjectUserAssignment(
                project_id=project_id,
                user_id=user.id,
                responsibility=responsibility,
                is_active=True,
                accepts_new_leads=True,
            ))
    db.add(user)


def sync_all_scope_users_for_project(db: Session, project: Project) -> None:
    users = db.query(User).filter(
        User.company_id == project.company_id,
        User.project_access_scope == "all",
        User.role.in_((UserRole.MKT, UserRole.SALES)),
    ).all()
    for user in users:
        responsibility = "sales" if user.role == UserRole.SALES else "marketing"
        assignment = db.query(ProjectUserAssignment).filter(
            ProjectUserAssignment.project_id == project.id,
            ProjectUserAssignment.user_id == user.id,
        ).first()
        if not assignment:
            assignment = ProjectUserAssignment(project_id=project.id, user_id=user.id)
        assignment.responsibility = responsibility
        assignment.is_active = True
        assignment.accepts_new_leads = True
        db.add(assignment)
