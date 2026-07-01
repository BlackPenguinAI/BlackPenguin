from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import uuid
from datetime import datetime

# Importamos los modelos y dependencias
from app.models.pg_models import get_db, Lead, User, UserRole, FunnelStage
from app.api.deps import RoleChecker

router = APIRouter()

# ==========================================
# ESQUEMAS PYDANTIC (Validación de datos)
# ==========================================
class LeadResponse(BaseModel):
    id: uuid.UUID
    project_id: Optional[uuid.UUID]
    full_name: str
    phone: str
    email: Optional[str]
    source: str
    intent_score: float
    is_opt_out: bool
    funnel_stage: FunnelStage
    created_at: datetime

    class Config:
        from_attributes = True

class LeadUpdate(BaseModel):
    funnel_stage: FunnelStage

# ==========================================
# ENDPOINTS (CRUD PARA VENTAS)
# ==========================================

@router.get("/", response_model=List[LeadResponse], summary="Listar Prospectos")
def list_leads(
    db: Session = Depends(get_db),
    # Permitimos acceso a Administradores, Marketing y Ventas
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    """
    Obtiene la lista cronológica de prospectos (Leads).
    Aislado automáticamente para mostrar solo los de la empresa del usuario.
    """
    leads = db.query(Lead).filter(
        Lead.company_id == current_user.company_id
    ).order_by(Lead.created_at.desc()).all()
    
    return leads

@router.put("/{lead_id}", response_model=LeadResponse, summary="Actualizar Estado del Prospecto")
def update_lead_status(
    lead_id: str,
    lead_in: LeadUpdate,
    db: Session = Depends(get_db),
    # Solo Administradores y Ventas deberían cambiar el estado de un lead
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))
):
    """
    Actualiza la etapa del embudo de ventas (funnel_stage) de un prospecto.
    Ejemplo: Mover de 'new' a 'contacted' o 'appointment_set'.
    """
    # Buscamos el lead ASEGURANDO que pertenezca a la empresa del usuario
    lead = db.query(Lead).filter(
        Lead.id == lead_id, 
        Lead.company_id == current_user.company_id
    ).first()
    
    if not lead:
        raise HTTPException(
            status_code=404, 
            detail="Prospecto no encontrado o no tienes permisos para editarlo."
        )
        
    # Actualizamos la etapa del embudo
    lead.funnel_stage = lead_in.funnel_stage
    db.commit()
    db.refresh(lead)
    
    return lead