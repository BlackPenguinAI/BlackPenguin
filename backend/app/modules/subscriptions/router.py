from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
# Nota temporal: Mantenemos el import de auth antiguo hasta la Fase 2
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from .schemas import SubscriptionPlanCreate, SubscriptionPlanUpdate, SubscriptionPlanResponse
from . import services

router = APIRouter()

@router.get("/", response_model=List[SubscriptionPlanResponse])
def list_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    """Obtiene todos los planes de suscripción."""
    return services.get_all_plans(db)

@router.post("/", response_model=SubscriptionPlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: SubscriptionPlanCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Crea un nuevo plan de suscripción."""
    return services.create_plan(db, payload)

@router.put("/{plan_id}", response_model=SubscriptionPlanResponse)
def update_plan(
    plan_id: str,
    payload: SubscriptionPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Actualiza un plan existente."""
    return services.update_plan(db, plan_id, payload)