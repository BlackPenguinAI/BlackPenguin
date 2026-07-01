from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import httpx
import uuid
import hmac
import hashlib

# Modelos e inyección de dependencias
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
    if settings.ENVIRONMENT == "local":
        return # Omitir verificación en desarrollo local si no se envían headers reales
        
    if not x_hub_signature_256:
        raise HTTPException(status_code=400, detail="Falta la cabecera de seguridad X-Hub-Signature-256.")
    
    signature = x_hub_signature_256.split("=")[1] if "=" in x_hub_signature_256 else x_hub_signature_256
    body = await request.body()
    
    expected_signature = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Firma criptográfica inválida. Petición no autorizada.")

# =================================================================
# AUXILIAR: EXTRACTOR ASÍNCRONO DE LEADS DESDE META GRAPH API
# =================================================================
async def fetch_lead_details_from_meta(leadgen_id: str) -> Optional[dict]:
    """
    Consulta de forma asíncrona a Meta Graph API para canjear el leadgen_id 
    por los datos reales del formulario (nombre, teléfono, correo).
    """
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{leadgen_id}"
    params = {
        "access_token": settings.META_ACCESS_TOKEN,
        "fields": "id,created_time,field_data"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                
                # Inicializamos nuestro diccionario de normalización
                lead_info = {"full_name": "N/A", "phone": "N/A", "email": "N/A"}
                
                # Mapeamos dinámicamente las respuestas del formulario de Meta
                for field in data.get("field_data", []):
                    field_name = field.get("name")
                    values = field.get("values", [])
                    field_value = values[0] if values else "N/A"
                    
                    if field_name in ["full_name", "full_name_facebook", "nombre_completo"]:
                        lead_info["full_name"] = field_value
                    elif field_name in ["phone", "phone_number", "telefono"]:
                        lead_info["phone"] = field_value
                    elif field_name in ["email", "correo_electronico"]:
                        lead_info["email"] = field_value
                        
                return lead_info
            else:
                return None
        except Exception:
            return None

# =================================================================
# RECEPCIÓN DE WEBHOOKS EN TIEMPO REAL (META ADS)
# =================================================================
@router.get("/meta", summary="Verificación de Webhook de Meta")
def verify_meta_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge")
):
    """
    Endpoint requerido por Meta para validar la autenticidad de la URL del webhook (Handshake).
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificación de Webhook inválido.")


@router.post("/meta", summary="Recepción de Leads en Tiempo Real (Meta)")
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Recibe la notificación de evento de Meta en tiempo real, canjea el leadgen_id
    por datos del usuario de forma asíncrona y realiza la ingesta aislada Multi-tenant.
    """
    # Descomentar la siguiente línea en producción cuando tengas configurado el META_APP_SECRET real
    # await verify_meta_signature(request, request.headers.get("X-Hub-Signature-256"))
    
    payload = await request.json()
    
    # Meta empaqueta las alertas dentro de estructuras anidadas de cambios estandarizados (entries)
    if "entry" in payload:
        for entry in payload["entry"]:
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    value = change.get("value", {})
                    leadgen_id = value.get("leadgen_id")
                    form_id = value.get("form_id")
                    
                    if not leadgen_id or not form_id:
                        continue
                        
                    # 1. Enrutamiento Inteligente: Buscamos a qué proyecto pertenece el form_id
                    mapping = db.query(MetaFormMapping).filter(MetaFormMapping.form_id == form_id).first()
                    if not mapping:
                        # Si no hay mapeo registrado para este formulario, ignoramos para proteger el aislamiento
                        continue
                        
                    project_id = mapping.project_id
                    company_id = mapping.company_id
                    
                    # 2. Canjeamos de forma asíncrona el leadgen_id por datos verdaderos
                    real_lead_data = await fetch_lead_details_from_meta(leadgen_id)
                    if not real_lead_data:
                        continue # Si Meta rechaza la petición, pasamos al siguiente cambio
                        
                    # 3. Persistencia en Base de Datos de forma aislada
                    new_lead = Lead(
                        company_id=company_id,
                        project_id=project_id,
                        full_name=real_lead_data["full_name"],
                        phone=real_lead_data["phone"],
                        email=real_lead_data["email"],
                        source="meta_ads"
                    )
                    db.add(new_lead)
                    db.commit()
                    
                    # TODO: [Semana 8 - Trigger] Despertar agente de IA enviando el lead_id recién creado.
                        
    return {"status": "success"}

# =================================================================
# ENDPOINT GENÉRICO (LANDING PAGES)
# =================================================================
@router.post("/landing-page", status_code=status.HTTP_201_CREATED, summary="Captura desde Landing Page")
def capture_landing_page_lead(payload: LeadCapturePayload, db: Session = Depends(get_db)) cavities=None):
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=\"El proyecto especificado no existe.\")
        
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
    return new_lead