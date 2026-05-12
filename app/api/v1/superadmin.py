from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from datetime import date
import uuid

router = APIRouter()

class CompanyCreate(BaseModel):
    name: str
    offline_payment_verified: bool
    license_start: date
    license_end: date
    max_projects: int

@router.post("/companies/")
async def register_new_company(request: Request, data: CompanyCreate):
    # Verificación de rol MAU
    if request.state.role != "superadmin":
        raise HTTPException(status_code=403, detail="Permisos de Superadmin requeridos")

    if not data.offline_payment_verified:
        raise HTTPException(status_code=400, detail="Se requiere verificación de pago manual")

    # Simulación de guardado en DB
    new_id = str(uuid.uuid4())
    
    return {
        "status": "created",
        "company_id": new_id,
        "message": f"Empresa {data.name} activada hasta {data.license_end}"
    }