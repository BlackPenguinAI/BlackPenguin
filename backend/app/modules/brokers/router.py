from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.projects.models import Project

from .models import Broker
from .schemas import BrokerCreate, BrokerResponse

router = APIRouter()

@router.get("/{project_id}/brokers", response_model=List[BrokerResponse])
def list_project_brokers(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))):
    return db.query(Broker).filter(Broker.project_id == project_id).all()

@router.post("/{project_id}/brokers", response_model=BrokerResponse)
def add_broker(project_id: str, payload: BrokerCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))):
    # Verificamos que el proyecto pertenezca a la compañía
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == current_user.company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
        
    new_broker = Broker(**payload.model_dump(), project_id=project_id)
    db.add(new_broker)
    db.commit()
    db.refresh(new_broker)
    return new_broker