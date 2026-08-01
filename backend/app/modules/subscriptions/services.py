from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import SubscriptionPlan
from .schemas import SubscriptionPlanCreate, SubscriptionPlanUpdate

def get_all_plans(db: Session):
    return db.query(SubscriptionPlan).order_by(SubscriptionPlan.name).all()

def create_plan(db: Session, payload: SubscriptionPlanCreate) -> SubscriptionPlan:
    existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un plan con ese nombre.")
    
    new_plan = SubscriptionPlan(**payload.model_dump())
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return new_plan
    
def update_plan(db: Session, plan_id: str, payload: SubscriptionPlanUpdate) -> SubscriptionPlan:
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan de suscripción no encontrado.")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)
        
    db.commit()
    db.refresh(plan)
    return plan