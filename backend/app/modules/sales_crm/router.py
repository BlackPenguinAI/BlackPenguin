from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.ai_core.services import get_ai_config
from app.integrations.openrouter_client import generate_llm_response

from .models import Lead, SmsChatMessage, Meeting, FunnelStage
from .schemas import LeadResponse, LeadUpdate, SmsChatMessageSchema, MeetingResponse, MeetingCreate, SalesReportResponse
from . import services
from app.modules.projects.models import Project, ProjectUnit

router = APIRouter()

# =========================================================
# 📊 LEADS & HISTORIAL DE CHAT SMS
# =========================================================
@router.get("/projects/{project_id}/leads-report", response_model=List[LeadResponse], summary="Reporte de Prospectos")
def get_leads_report(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    return services.get_project_leads(db, current_user.company_id, project_id, sales_user_id)

@router.get("/leads/{lead_id}/chat", response_model=List[SmsChatMessageSchema], summary="Historial de Chat SMS con el Lead")
def get_lead_chat(
    lead_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    return services.get_lead_sms_chat(db, lead_id, current_user.company_id)

@router.put("/leads/{lead_id}", response_model=LeadResponse, summary="Actualizar Etapa del Embudo del Prospecto")
def update_lead_status(
    lead_id: str,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))
):
    return services.update_lead(db, lead_id, current_user.company_id, payload, current_user.id)

# =========================================================
# 📈 SALES REPORT (Inventario, Revenue, ROI y Coordenadas Mapa)
# =========================================================
@router.get("/projects/{project_id}/sales-report", response_model=SalesReportResponse, summary="Reporte de Ventas e Inventario")
def get_sales_report(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    project = db.query(Project).filter(
        Project.id == project_id, Project.company_id == current_user.company_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    leads = db.query(Lead).filter(Lead.project_id == project_id, Lead.company_id == current_user.company_id).all()
    units = db.query(ProjectUnit).filter(ProjectUnit.project_id == project_id).all()
    
    leads_map = [
        {"id": l.id, "name": l.full_name, "lat": l.latitude, "lng": l.longitude, "stage": l.funnel_stage}
        for l in leads if l.latitude and l.longitude
    ]
    
    sold_units = [unit for unit in units if unit.status == "sold"]
    available_units = [unit for unit in units if unit.status == "available"]
    priced_sold_units = [unit for unit in sold_units if unit.list_price is not None]
    total_revenue = sum(float(unit.list_price) for unit in priced_sold_units) if priced_sold_units else None
    inventory_status = (
        f"{len(available_units)} available / {len(sold_units)} sold" if units else None
    )
    return {
        "inventory_status": inventory_status,
        "total_revenue": total_revenue,
        "target_roi": None,
        "unit_inventory": [{
            "unit": unit.unit_code, "type": unit.typology, "price": float(unit.list_price) if unit.list_price is not None else None,
            "currency": unit.currency, "status": unit.status,
        } for unit in units],
        "leads_map": leads_map,
        "calculation_status": "available" if units else "pending",
        "generated_at": datetime.utcnow() if units else None,
    }

# =========================================================
# 📅 MEETING MANAGEMENT (Citas Agendadas e Integración GCalendar)
# =========================================================
@router.get("/projects/{project_id}/meetings", response_model=List[MeetingResponse], summary="Lista de Citas Agendadas")
def get_meetings(
    project_id: str,
    broker_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))
):
    sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    meetings = services.get_project_meetings(db, current_user.company_id, project_id, broker_id, sales_user_id)
    response = []
    for m in meetings:
        item = MeetingResponse.model_validate(m)
        if m.lead:
            item.lead_name = m.lead.full_name
        response.append(item)
    return response

@router.post("/meetings", response_model=MeetingResponse, summary="Crear o Agendar Cita")
def schedule_meeting(
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.SALES]))
):
    assigned_sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    return services.create_meeting(db, payload, current_user.company_id, assigned_sales_user_id)

# =========================================================
# 📲 TWILIO SMS WEBHOOK (Entrada de mensajes del prospecto)
# =========================================================
@router.post("/webhook/twilio", summary="Webhook entrante de Twilio SMS")
async def twilio_sms_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db)
):
    # 1. Buscar prospecto por teléfono
    lead = db.query(Lead).filter(Lead.phone == From).first()
    if not lead:
        return {"status": "ignored", "reason": "Número no registrado"}

    # 2. Guardar mensaje del prospecto
    user_msg = SmsChatMessage(lead_id=lead.id, role="user", content=Body)
    db.add(user_msg)
    db.commit()

    # 3. Consultar configuración del Agente de Ventas
    ai_config = get_ai_config(db, company_id=lead.company_id)
    agent_config = ai_config.agent_ventas
    
    system_instruction = f"{agent_config.get('system_prompt', '')}\n\nProtocolo:\n{agent_config.get('protocol_prompt', '')}\n\nGuardrails:\n{agent_config.get('guardrails_prompt', '')}"
    
    chat_history = db.query(SmsChatMessage).filter(SmsChatMessage.lead_id == lead.id).order_by(SmsChatMessage.created_at.asc()).all()
    messages_payload = [{"role": "system", "content": system_instruction}]
    for msg in chat_history[-10:]:
        messages_payload.append({"role": "user" if msg.role == "user" else "assistant", "content": msg.content})

    # 4. Generar respuesta con la IA de Ventas
    model = agent_config.get("model", "openai/gpt-4o-mini")
    ai_reply = await generate_llm_response(ai_config.openrouter_api_key, model, messages_payload)

    # 5. Guardar respuesta del Agente
    ai_msg = SmsChatMessage(lead_id=lead.id, role="assistant", content=ai_reply)
    db.add(ai_msg)
    db.commit()

    return {"status": "success", "reply": ai_reply}
