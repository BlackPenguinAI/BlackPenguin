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
    existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == plan_in.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plan with this name already exists")
    
    new_plan = SubscriptionPlan(
        name=plan_in.name,
        description=plan_in.description,
        max_admins=plan_in.max_admins,
        max_mkt_users=plan_in.max_mkt_users,
        max_sales_users=plan_in.max_sales_users,
        max_projects=plan_in.max_projects,
        max_properties_per_project=plan_in.max_properties_per_project,
        is_active=plan_in.is_active
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
    plan.description = plan_in.description
    plan.max_admins = plan_in.max_admins
    plan.max_mkt_users = plan_in.max_mkt_users
    plan.max_sales_users = plan_in.max_sales_users
    plan.max_projects = plan_in.max_projects
    plan.max_properties_per_project = plan_in.max_properties_per_project
    plan.is_active = plan_in.is_active
    
    db.commit()
    db.refresh(plan)
    return plan

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