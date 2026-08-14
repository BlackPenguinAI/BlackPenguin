from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.users.models import User

from .models import ProjectRoutingState, ProjectUserAssignment


ROUND_ROBIN_DESCRIPTION = (
    "Round robin assigns each new lead or appointment to the next active Sales user "
    "assigned to the project. Managers can always reassign it manually."
)


def eligible_sales_assignments(db: Session, project_id: str) -> list[ProjectUserAssignment]:
    return (
        db.query(ProjectUserAssignment)
        .join(User, User.id == ProjectUserAssignment.user_id)
        .filter(
            ProjectUserAssignment.project_id == project_id,
            ProjectUserAssignment.responsibility == "sales",
            ProjectUserAssignment.is_active.is_(True),
            ProjectUserAssignment.accepts_new_leads.is_(True),
            User.is_active.is_(True),
        )
        .order_by(ProjectUserAssignment.created_at.asc(), ProjectUserAssignment.user_id.asc())
        .all()
    )


def select_next_sales_user(db: Session, project_id: str) -> str | None:
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
    assignments = eligible_sales_assignments(db, project_id)
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
