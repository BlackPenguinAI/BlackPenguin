from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from .models import SubscriptionPlan
from .schemas import PlanCreate, PlanResponse

router = APIRouter()

@router.post("/", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    plan_in: PlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    # Verificar si el plan ya existe por nombre
    existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == plan_in.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plan with this name already exists")
    
    new_plan = SubscriptionPlan(
        name=plan_in.name,
        max_users=plan_in.max_users,
        base_price=plan_in.base_price
    )
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return new_plan

@router.get("/", response_model=List[PlanResponse])
def get_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.created_at.desc()).all()
    return plans

# 🚀 NUEVO: ACTUALIZAR PLAN
@router.put("/{plan_id}/", response_model=PlanResponse, status_code=status.HTTP_200_OK)
def update_plan(
    plan_id: str,
    plan_in: PlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    plan.name = plan_in.name
    plan.max_users = plan_in.max_users
    plan.base_price = plan_in.base_price
    
    db.commit()
    db.refresh(plan)
    return plan

# 🚀 NUEVO: ELIMINAR PLAN
@router.delete("/{plan_id}/", status_code=status.HTTP_200_OK)
def delete_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    db.delete(plan)
    db.commit()
    return {"detail": "Plan deleted successfully"}