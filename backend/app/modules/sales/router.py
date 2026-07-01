from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.sales.models import Lead
from app.modules.sales.schemas import LeadResponse, LeadUpdate
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

router = APIRouter()

@router.get("/", response_model=List[LeadResponse], summary="Listar Prospectos")
def list_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    """Obtiene la lista cronológica de prospectos (Aislado al Tenant)."""
    return db.query(Lead).filter(
        Lead.company_id == current_user.company_id
    ).order_by(Lead.created_at.desc()).all()

@router.put("/{lead_id}", response_model=LeadResponse, summary="Actualizar Estado del Prospecto")
def update_lead_status(
    lead_id: str,
    lead_in: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))
):
    """Actualiza la etapa del embudo de ventas (funnel_stage)."""
    lead = db.query(Lead).filter(
        Lead.id == lead_id, 
        Lead.company_id == current_user.company_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado.")
        
    lead.funnel_stage = lead_in.funnel_stage
    db.commit()
    db.refresh(lead)
    
    return lead