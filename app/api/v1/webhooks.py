from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import uuid

from app.models.pg_models import get_db, Lead, Project

router = APIRouter()

# --- ESQUEMAS DE VALIDACIÓN ---
class LeadCapturePayload(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    project_id: str

# =================================================================
# 1. ENDPOINTS DE META ADS (FACEBOOK / INSTAGRAM)
# =================================================================

@router.get("/meta", summary="Verificación de Webhook de Meta")
def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: int = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """
    Endpoint obligatorio de Meta. Facebook envía una petición GET con un 'challenge'
    y un token secreto para verificar que eres el dueño del servidor.
    """
    VERIFY_TOKEN = "blackpenguin_meta_token_2026" # En producción, esto viene de .env
    
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Fallo en la verificación del token de Meta.")

@router.post("/meta", summary="Recepción de Leads en Tiempo Real (Meta)")
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint donde Meta enviará un POST cada vez que un usuario llene un formulario de anuncios.
    """
    payload = await request.json()
    
    if payload.get("object") == "page":
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    leadgen_info = change.get("value", {})
                    lead_id_meta = leadgen_info.get("leadgen_id", "Desconocido")
                    
                    # *Nota para producción: Aquí consultarías la Graph API de Meta usando el lead_id_meta
                    # para obtener los campos reales (nombre, teléfono).
                    
                    # Simulamos la ingesta asignándolo al primer proyecto encontrado para propósitos del MVP
                    project = db.query(Project).first()
                    if project:
                        new_lead = Lead(
                            company_id=project.company_id,
                            project_id=project.id,
                            full_name=f"Lead de Meta (ID: {lead_id_meta[-4:]})",
                            phone="+520000000000",
                            email="prospecto@meta.com",
                            source="meta_ads",
                        )
                        db.add(new_lead)
                        db.commit()
                        
    return {"status": "success", "message": "Webhook procesado exitosamente"}

# =================================================================
# 2. ENDPOINT GENÉRICO (LANDING PAGES O CRMS TERCEROS)
# =================================================================

@router.post("/landing-page", status_code=status.HTTP_201_CREATED, summary="Captura desde Landing Page")
def capture_landing_page_lead(payload: LeadCapturePayload, db: Session = Depends(get_db)):
    """
    Recibe un lead directamente desde un formulario web propio o integración de terceros.
    """
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="El proyecto especificado no existe en Black Penguin.")
        
    new_lead = Lead(
        company_id=project.company_id,
        project_id=project.id,
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        source="landing_page"
    )
    
    db.add(new_lead)
    db.commit()
    db.refresh(new_lead)
    
    return {"status": "success", "message": "Lead capturado", "lead_id": new_lead.id}