from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel, EmailStr # 🚀 Añadido
import os # 🚀 Añadido
import httpx # 🚀 Añadido

from app.db.postgres import get_db
from app.modules.sales.models import Lead
from app.modules.sales.schemas import LeadResponse, LeadUpdate
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

router = APIRouter()

# =================================================================
# 🚀 1. NUEVO ENDPOINT: INTEGRACIÓN CON MAILCHIMP (WAITLIST)
# =================================================================
class WaitlistRequest(BaseModel):
    email: EmailStr

@router.post("/waitlist", summary="Unirse a la lista de espera (Mailchimp)")
async def join_waitlist(payload: WaitlistRequest):
    api_key = os.getenv("MAILCHIMP_API_KEY")
    list_id = os.getenv("MAILCHIMP_LIST_ID")
    server = os.getenv("MAILCHIMP_SERVER")

    # Si no has puesto las keys aún, el sistema simula éxito para que puedas probar local
    if not api_key or not list_id or not server:
        print(f"✅ Waitlist local simulado para: {payload.email}")
        return {"message": "Suscrito exitosamente (Modo Local/Desarrollo)"}

    url = f"https://{server}.api.mailchimp.com/3.0/lists/{list_id}/members"
    data = {
        "email_address": payload.email,
        "status": "subscribed"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, auth=("anonym", api_key), json=data)
        
        if response.status_code in [200, 204]:
            return {"message": "¡Suscrito exitosamente!"}
        elif response.status_code == 400 and "Member Exists" in response.text:
            return {"message": "El correo ya está registrado en la lista de espera."}
        else:
            raise HTTPException(status_code=400, detail="Error al procesar la solicitud.")


# =================================================================
# 2. ENDPOINTS ORIGINALES DE VENTAS (MANTENIDOS INTACTOS)
# =================================================================
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
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == current_user.company_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Prospecto no encontrado.")
    
    lead.funnel_stage = lead_in.funnel_stage
    db.commit()
    db.refresh(lead)
    return lead