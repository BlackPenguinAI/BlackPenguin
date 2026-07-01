from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
import httpx

from app.db.postgres import get_db
from app.core.config import settings
from app.modules.sales.models import Lead
from app.modules.properties.models import Project
from app.modules.integrations.models import MetaFormMapping
from app.modules.integrations.schemas import LeadCapturePayload

router = APIRouter()

async def fetch_lead_details_from_meta(leadgen_id: str):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{leadgen_id}"
    params = {"access_token": settings.META_ACCESS_TOKEN, "fields": "id,field_data"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                lead_info = {"full_name": "N/A", "phone": "N/A", "email": "N/A"}
                for field in data.get("field_data", []):
                    name = field.get("name")
                    val = field.get("values", [])[0] if field.get("values") else "N/A"
                    if name in ["full_name", "nombre_completo"]: lead_info["full_name"] = val
                    elif name in ["phone", "phone_number", "telefono"]: lead_info["phone"] = val
                    elif name in ["email", "correo_electronico"]: lead_info["email"] = val
                return lead_info
        except Exception:
            return None
    return None

@router.get("/meta")
def verify_meta_webhook(hub_mode: str = Query(..., alias="hub.mode"), hub_verify_token: str = Query(..., alias="hub.verify_token"), hub_challenge: str = Query(..., alias="hub.challenge")):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token inválido.")

@router.post("/meta")
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    if "entry" in payload:
        for entry in payload["entry"]:
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    val = change.get("value", {})
                    leadgen_id, form_id = val.get("leadgen_id"), val.get("form_id")
                    if not leadgen_id or not form_id: continue
                    
                    mapping = db.query(MetaFormMapping).filter(MetaFormMapping.form_id == form_id).first()
                    if not mapping: continue
                        
                    real_data = await fetch_lead_details_from_meta(leadgen_id)
                    if real_data:
                        db.add(Lead(company_id=mapping.company_id, project_id=mapping.project_id, source="meta_ads", **real_data))
                        db.commit()
    return {"status": "success"}

@router.post("/landing-page", status_code=status.HTTP_201_CREATED)
def capture_landing_page_lead(payload: LeadCapturePayload, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project: raise HTTPException(status_code=404)
    db.add(Lead(company_id=project.company_id, project_id=project.id, source="landing_page", **payload.model_dump(exclude={"project_id"})))
    db.commit()
    return {"status": "success"}