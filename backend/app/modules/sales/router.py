from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel, EmailStr
from datetime import datetime

from app.db.postgres import get_db
from app.modules.sales.models import Lead, WaitlistEmail 
from app.modules.sales.schemas import LeadResponse, LeadUpdate
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

router = APIRouter()

# =================================================================
# 🚀 ENDPOINTS: LISTA DE ESPERA (POSTGRESQL NATIVO)
# =================================================================
class WaitlistRequest(BaseModel):
    email: EmailStr

class WaitlistResponse(BaseModel):
    id: str
    email: str
    created_at: datetime
    class Config:
        from_attributes = True

@router.post("/waitlist", summary="Unirse a la lista de espera")
def join_waitlist(payload: WaitlistRequest, db: Session = Depends(get_db)):
    existing_email = db.query(WaitlistEmail).filter(WaitlistEmail.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Este correo ya se encuentra en la lista de espera.")
    
    new_email = WaitlistEmail(email=payload.email)
    db.add(new_email)
    db.commit()
    return {"message": "¡Suscrito exitosamente a la lista de espera!"}

@router.get("/waitlist", response_model=List[WaitlistResponse], summary="Obtener correos (Solo Admin)")
def get_waitlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    return db.query(WaitlistEmail).order_by(WaitlistEmail.created_at.desc()).all()

# 🚀 NUEVO: Endpoint para EDITAR
@router.put("/waitlist/{email_id}", response_model=WaitlistResponse, summary="Actualizar correo (Solo Admin)")
def update_waitlist_email(
    email_id: str,
    payload: WaitlistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    email_record = db.query(WaitlistEmail).filter(WaitlistEmail.id == email_id).first()
    if not email_record:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    
    # Validar que el nuevo correo no choque con otro existente
    if payload.email != email_record.email:
        existing = db.query(WaitlistEmail).filter(WaitlistEmail.email == payload.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Este correo ya pertenece a otro registro.")
            
    email_record.email = payload.email
    db.commit()
    db.refresh(email_record)
    return email_record

# 🚀 NUEVO: Endpoint para ELIMINAR
@router.delete("/waitlist/{email_id}", summary="Eliminar correo (Solo Admin)")
def delete_waitlist_email(
    email_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    email_record = db.query(WaitlistEmail).filter(WaitlistEmail.id == email_id).first()
    if not email_record:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
        
    db.delete(email_record)
    db.commit()
    return {"message": "Registro eliminado exitosamente."}

# =================================================================
# ENDPOINTS ORIGINALES DE VENTAS (CRUD LEAD)
# =================================================================
@router.get("/", response_model=List[LeadResponse], summary="Listar Prospectos")
def list_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
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
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == current_user.company_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado.")
    
    lead.funnel_stage = lead_in.funnel_stage
    db.commit()
    db.refresh(lead)
    return lead