from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.projects.models import Project
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users import services as user_services
from app.modules.users.schemas import TenantUserResponse
from app.modules.users.project_access import require_project_access

from .models import ProjectUserAssignment
from .schemas import AssignmentResponse, AssignmentUpsert, RoutingPolicyResponse, SalesUserInviteAndAssign
from .service import ROUND_ROBIN_DESCRIPTION, eligible_sales_assignments


router = APIRouter()


def _project(db: Session, project_id: str, current_user: User) -> Project:
    require_project_access(db, current_user, project_id)
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == current_user.company_id).first()
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
    _project(db, project_id, current_user)
    items = db.query(ProjectUserAssignment).options(joinedload(ProjectUserAssignment.user)).filter(
        ProjectUserAssignment.project_id == project_id,
    ).order_by(ProjectUserAssignment.responsibility, ProjectUserAssignment.is_primary.desc()).all()
    return [_serialize(item) for item in items]


@router.get("/{project_id}/team/candidates", response_model=list[TenantUserResponse])
def list_sales_candidates(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _project(db, project_id, current_user)
    return db.query(User).filter(
        User.company_id == current_user.company_id,
        User.role == UserRole.SALES,
        User.is_active.is_(True),
    ).order_by(User.email.asc()).all()


@router.put("/{project_id}/team/{user_id}", response_model=AssignmentResponse)
def upsert_assignment(
    project_id: str,
    user_id: str,
    payload: AssignmentUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _project(db, project_id, current_user)
    if payload.user_id != user_id:
        raise HTTPException(status_code=422, detail="Path and payload user IDs differ.")
    user = db.query(User).filter(User.id == user_id, User.company_id == current_user.company_id).first()
    expected_role = UserRole.MKT if payload.responsibility == "marketing" else UserRole.SALES
    if not user or user.role != expected_role or not user.is_active:
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


@router.post("/{project_id}/team/invite-sales", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def invite_and_assign_sales_user(
    project_id: str,
    payload: SalesUserInviteAndAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _project(db, project_id, current_user)
    try:
        user = user_services.invite_tenant_user(
            db,
            company_id=current_user.company_id,
            email=str(payload.email),
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=UserRole.SALES,
            project_access_scope="selected",
            project_ids=[project_id],
            commit=False,
            send_activation_email=False,
        )
        if payload.is_primary:
            db.query(ProjectUserAssignment).filter(
                ProjectUserAssignment.project_id == project_id,
                ProjectUserAssignment.responsibility == "sales",
            ).update({ProjectUserAssignment.is_primary: False}, synchronize_session=False)
        assignment = db.query(ProjectUserAssignment).filter(
            ProjectUserAssignment.project_id == project_id,
            ProjectUserAssignment.user_id == user.id,
        ).one()
        assignment.is_primary = payload.is_primary
        db.commit()
        assignment = db.query(ProjectUserAssignment).options(joinedload(ProjectUserAssignment.user)).filter(
            ProjectUserAssignment.id == assignment.id,
        ).one()
    except Exception:
        db.rollback()
        raise
    try:
        user_services.provision_invitation(
            db, user=user, invited_by_user_id=current_user.id,
        )
    except Exception:
        pass
    return _serialize(assignment)


@router.get("/{project_id}/routing-policy", response_model=RoutingPolicyResponse)
def get_routing_policy(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    _project(db, project_id, current_user)
    return {
        "policy": "round_robin",
        "description": ROUND_ROBIN_DESCRIPTION,
        "eligible_sales_users": len(eligible_sales_assignments(db, project_id)),
        "manual_reassignment_allowed": True,
    }


@router.delete("/{project_id}/team/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    project_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _project(db, project_id, current_user)
    db.query(ProjectUserAssignment).filter(
        ProjectUserAssignment.project_id == project_id,
        ProjectUserAssignment.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
