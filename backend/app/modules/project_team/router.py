from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.projects.models import Project
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole

from .models import ProjectUserAssignment
from .schemas import AssignmentResponse, AssignmentUpsert


router = APIRouter()


def _project(db: Session, project_id: str, company_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _serialize(item: ProjectUserAssignment) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "user_id": item.user_id,
        "responsibility": item.responsibility,
        "is_primary": item.is_primary,
        "routing_weight": item.routing_weight,
        "accepts_new_leads": item.accepts_new_leads,
        "is_active": item.is_active,
        "email": item.user.email,
        "first_name": item.user.first_name,
        "last_name": item.user.last_name,
    }


@router.get("/{project_id}/team", response_model=list[AssignmentResponse])
def list_team(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    _project(db, project_id, current_user.company_id)
    items = db.query(ProjectUserAssignment).options(joinedload(ProjectUserAssignment.user)).filter(
        ProjectUserAssignment.project_id == project_id,
    ).order_by(ProjectUserAssignment.responsibility, ProjectUserAssignment.is_primary.desc()).all()
    return [_serialize(item) for item in items]


@router.put("/{project_id}/team/{user_id}", response_model=AssignmentResponse)
def upsert_assignment(
    project_id: str,
    user_id: str,
    payload: AssignmentUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _project(db, project_id, current_user.company_id)
    if payload.user_id != user_id:
        raise HTTPException(status_code=422, detail="Path and payload user IDs differ.")
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    expected_role = UserRole.MKT if payload.responsibility == "marketing" else UserRole.SALES
    if not user or user.role != expected_role:
        raise HTTPException(status_code=422, detail=f"A {payload.responsibility} assignment requires a matching active Company user.")
    item = db.query(ProjectUserAssignment).filter(
        ProjectUserAssignment.project_id == project_id,
        ProjectUserAssignment.user_id == user_id,
    ).first() or ProjectUserAssignment(project_id=project_id, user_id=user_id)
    for key, value in payload.model_dump(exclude={"user_id"}).items():
        setattr(item, key, value)
    if payload.is_primary:
        db.query(ProjectUserAssignment).filter(
            ProjectUserAssignment.project_id == project_id,
            ProjectUserAssignment.responsibility == payload.responsibility,
            ProjectUserAssignment.user_id != user_id,
        ).update({ProjectUserAssignment.is_primary: False}, synchronize_session=False)
    db.add(item)
    db.commit()
    item = db.query(ProjectUserAssignment).options(joinedload(ProjectUserAssignment.user)).filter(ProjectUserAssignment.id == item.id).one()
    return _serialize(item)


@router.delete("/{project_id}/team/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    project_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _project(db, project_id, current_user.company_id)
    db.query(ProjectUserAssignment).filter(
        ProjectUserAssignment.project_id == project_id,
        ProjectUserAssignment.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
