from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import httpx
import uuid
import hmac
import hashlib

# Añadimos MetaFormMapping a la importación
from app.models.pg_models import get_db, Lead, Project, MetaFormMapping
from app.core.config import settings

router = APIRouter()

class LeadCapturePayload(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    project_id: str

# =================================================================
# SEGURIDAD CRIPTOGRÁFICA (HMAC-SHA256)
# =================================================================
async def verify_meta_signature(request: Request, x_hub_signature_256: str = Header(None)):
    """
    Verifica que la petición provenga genuinamente de los servidores de Meta
    comparando la firma criptográfica enviada en los headers.
    """
    if not x_hub_signature_256:
        raise HTTPException(status_code=400, detail="Falta la cabecera de seguridad X-Hub-Signature-256.")
    
    # Extraemos la firma que viene en formato "sha256=abcdef1234..."
    signature = x_hub_signature_256.split("=")[1] if "=" in x_hub_signature_256 else x_hub_signature_256
    
    # Leemos el cuerpo en crudo (bytes) antes de que FastAPI lo convierta a JSON
    body = await request.body()
    
    # Calculamos nuestro propio hash usando el App Secret
    expected_hash = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Comparamos de forma segura para evitar Timing Attacks
    if not hmac.compare_digest(expected_hash, signature):
        raise HTTPException(status_code=403, detail="Firma criptográfica inválida. Intento de inyección bloqueado.")

# =================================================================
# FUNCIÓN ASÍNCRONA PARA EXTRAER DATOS REALES DE META
# =================================================================
async def fetch_meta_lead_data(leadgen_id: str) -> dict:
    """
    Se conecta a la Graph API de Meta para canjear el leadgen_id por los datos reales.
    """
    url = f"https://graph.facebook.com/v19.0/{leadgen_id}"
    params = {
        "access_token": settings.META_ACCESS_TOKEN
    }
    
    extracted_data = {
        "full_name": "Lead sin nombre",
        "email": "sin_correo@lead.com",
        "phone": "0000000000"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        
        if response.status_code == 200:
            meta_payload = response.json()
            for field in meta_payload.get("field_data", []):
                field_name = field.get("name")
                field_value = field.get("values", [""])[0]
                
                if field_name == "full_name":
                    extracted_data["full_name"] = field_value
                elif field_name == "email":
                    extracted_data["email"] = field_value
                elif field_name in ["phone_number", "phone"]:
                    extracted_data["phone"] = field_value
        else:
            extracted_data["full_name"] = f"Error Meta API: {response.status_code}"

    return extracted_data

# =================================================================
# ENDPOINTS DE META ADS
# =================================================================

@router.get("/meta", summary="Verificación de Webhook de Meta")
def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: int = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Fallo en la verificación del token de Meta.")

@router.post("/meta", summary="Recepción de Leads en Tiempo Real (Meta)")
async def receive_meta_webhook(
    request: Request, 
    db: Session = Depends(get_db)
):
    # 1. EJECUTAMOS LA DEFENSA CRIPTOGRÁFICA
    await verify_meta_signature(request, request.headers.get("X-Hub-Signature-256"))
    
    # 2. Si pasa la seguridad, procesamos el webhook normalmente
    payload = await request.json()
    
    if payload.get("object") == "page":
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    leadgen_info = change.get("value", {})
                    lead_id_meta = leadgen_info.get("leadgen_id")
                    form_id_meta = leadgen_info.get("form_id") # <-- Extraemos el ID del formulario de Meta
                    
                    if not lead_id_meta or not form_id_meta:
                        continue
                    
                    real_lead_data = await fetch_meta_lead_data(lead_id_meta)
                    
                    # 3. ENRUTAMIENTO INTELIGENTE: Buscamos a quién pertenece este formulario
                    mapping = db.query(MetaFormMapping).filter(MetaFormMapping.meta_form_id == str(form_id_meta)).first()
                    
                    if mapping:
                        company_id = mapping.company_id
                        project_id = mapping.project_id
                    else:
                        # Fallback de emergencia: si olvidaron mapearlo, lo metemos al primer proyecto
                        fallback_project = db.query(Project).first()
                        if not fallback_project:
                            continue
                        company_id = fallback_project.company_id
                        project_id = fallback_project.id
                        # Dejamos una advertencia en el nombre para el vendedor
                        real_lead_data["full_name"] = f"[SIN MAPEO - Form: {form_id_meta[-4:]}] {real_lead_data['full_name']}"
                    
                    # 4. Inserción aislada en Base de Datos
                    new_lead = Lead(
                        company_id=company_id,
                        project_id=project_id,
                        full_name=real_lead_data["full_name"],
                        phone=real_lead_data["phone"],
                        email=real_lead_data["email"],
                        source="meta_ads",
                    )
                    db.add(new_lead)
                    db.commit()
                        
    return {"status": "success"}

# =================================================================
# ENDPOINT GENÉRICO (LANDING PAGES)
# =================================================================

@router.post("/landing-page", status_code=status.HTTP_201_CREATED, summary="Captura desde Landing Page")
def capture_landing_page_lead(payload: LeadCapturePayload, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="El proyecto especificado no existe.")
        
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