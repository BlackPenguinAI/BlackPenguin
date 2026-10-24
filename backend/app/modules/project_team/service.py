from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.users.models import SALES_ACTOR_ROLES, User

from .models import ProjectRoutingState, ProjectUserAssignment


ROUND_ROBIN_DESCRIPTION = (
    "Round robin assigns each new lead or appointment to the next active Sales-capable user "
    "assigned to the project. A Company Administrator may be assigned for end-to-end testing "
    "without creating another user. Managers can always reassign it manually."
)


def _sales_assignments(db: Session, project_id: str, *, for_appointments: bool) -> list[ProjectUserAssignment]:
    capability = (
        ProjectUserAssignment.accepts_appointments
        if for_appointments else ProjectUserAssignment.accepts_new_leads
    )
    return (
        db.query(ProjectUserAssignment)
        .join(User, User.id == ProjectUserAssignment.user_id)
        .filter(
            ProjectUserAssignment.project_id == project_id,
            ProjectUserAssignment.sales_enabled.is_(True),
            ProjectUserAssignment.is_active.is_(True),
            capability.is_(True),
            User.is_active.is_(True),
            User.role.in_(SALES_ACTOR_ROLES),
        )
        .order_by(ProjectUserAssignment.created_at.asc(), ProjectUserAssignment.user_id.asc())
        .all()
    )


def eligible_lead_routing_assignments(db: Session, project_id: str) -> list[ProjectUserAssignment]:
    """Sales-capable users that may receive a new lead through round robin."""
    return _sales_assignments(db, project_id, for_appointments=False)


def eligible_appointment_assignments(db: Session, project_id: str) -> list[ProjectUserAssignment]:
    """Sales-capable users whose availability may be offered for appointments."""
    return _sales_assignments(db, project_id, for_appointments=True)


def eligible_sales_assignments(db: Session, project_id: str) -> list[ProjectUserAssignment]:
    """Backward-compatible alias for lead-routing eligibility."""
    return eligible_lead_routing_assignments(db, project_id)


def select_next_sales_user(
    db: Session,
    project_id: str,
    *,
    eligible_user_ids: set[str] | None = None,
    for_appointments: bool = False,
) -> str | None:
    """Select the next eligible user while locking the project routing cursor."""
    state = (
        db.query(ProjectRoutingState)
        .filter(ProjectRoutingState.project_id == project_id)
        .with_for_update()
        .first()
    )
    if not state:
        state = ProjectRoutingState(project_id=project_id, policy="round_robin")
        db.add(state)
        db.flush()
    assignments = (
        eligible_appointment_assignments(db, project_id)
        if for_appointments else eligible_lead_routing_assignments(db, project_id)
    )
    if eligible_user_ids is not None:
        assignments = [item for item in assignments if item.user_id in eligible_user_ids]
    if not assignments:
        return None
    ids = [item.user_id for item in assignments]
    try:
        current_index = ids.index(state.last_assigned_user_id) if state.last_assigned_user_id else -1
    except ValueError:
        current_index = -1
    selected_id = ids[(current_index + 1) % len(ids)]
    state.last_assigned_user_id = selected_id
    state.assignment_sequence += 1
    db.add(state)
    db.flush()
    return selected_id
