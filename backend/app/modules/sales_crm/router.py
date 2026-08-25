from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
import uuid

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.ai_core.services import get_ai_config
from app.integrations.openrouter_client import generate_llm_response

from .models import Lead, SmsChatMessage, Meeting, MeetingAttachment, MeetingStatus, SalesAvailabilityBlock, FunnelStage
from .schemas import (
    AvailabilityBlockCreate, AvailabilityBlockResponse, AvailabilityUpdate, AvailabilityWindowResponse,
    CalendarConnectionResponse, CalendarConnectionUpdate, LeadResponse, LeadUpdate,
    ManagerSalesScheduleResponse, MeetingAttachmentResponse, MeetingCreate, MeetingResponse, MeetingUpdate,
    SalesLeadDetailResponse, SalesReportResponse, SalesScheduleResponse, SmsChatMessageSchema,
)
from . import services
from . import scheduling
from . import storage_service
from app.modules.projects.models import Project, ProjectUnit

router = APIRouter()

ATTACHMENT_RULES = {
    "visit_photo": ({"image/jpeg", "image/png", "image/webp"}, 10 * 1024 * 1024),
    "sale_evidence": ({"image/jpeg", "image/png", "image/webp", "application/pdf"}, 15 * 1024 * 1024),
}


def _meeting_response(meeting: Meeting, db: Session) -> MeetingResponse:
    item = MeetingResponse.model_validate(meeting)
    project = db.query(Project).filter(Project.id == meeting.project_id).first()
    if project:
        item.project_name = project.name
        item.project_address = project.address
        item.project_timezone = project.timezone or "UTC"
    if meeting.lead:
        item.lead_name = meeting.lead.full_name
    if meeting.assigned_sales_user_id:
        user = db.query(User).filter(User.id == meeting.assigned_sales_user_id).first()
        if user:
            item.sales_user_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.email
    item.attachments = [
        MeetingAttachmentResponse.model_validate(attachment).model_copy(update={
            "download_url": f"/api/v1/sales/meetings/{meeting.id}/attachments/{attachment.id}",
        }) for attachment in meeting.attachments
    ]
    return item

# =========================================================
# 📊 LEADS & HISTORIAL DE CHAT SMS
# =========================================================
@router.get("/projects/{project_id}/leads-report", response_model=List[LeadResponse], summary="Reporte de Prospectos")
def get_leads_report(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES]))
):
    sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    return services.get_project_leads(db, current_user.company_id, project_id, sales_user_id)

@router.get("/leads/{lead_id}/chat", response_model=List[SmsChatMessageSchema], summary="Historial de Chat SMS con el Lead")
def get_lead_chat(
    lead_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES]))
):
    return services.get_lead_sms_chat(
        db, lead_id, current_user.company_id,
        current_user.id if current_user.role == UserRole.SALES else None,
    )


@router.get("/leads/{lead_id}", response_model=SalesLeadDetailResponse, summary="Lead detail for Marketing and assigned Sales")
def get_lead_detail(
    lead_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    return services.get_lead_detail(
        db, lead_id, current_user.company_id,
        current_user.id if current_user.role == UserRole.SALES else None,
    )

@router.put("/leads/{lead_id}", response_model=LeadResponse, summary="Actualizar Etapa del Embudo del Prospecto")
def update_lead_status(
    lead_id: str,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES]))
):
    return services.update_lead(
        db, lead_id, current_user.company_id, payload, current_user.id,
        current_user.id if current_user.role == UserRole.SALES else None,
    )

# =========================================================
# 📈 SALES REPORT (Inventario, Revenue, ROI y Coordenadas Mapa)
# =========================================================
@router.get("/projects/{project_id}/sales-report", response_model=SalesReportResponse, summary="Reporte de Ventas e Inventario")
def get_sales_report(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES]))
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
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES]))
):
    sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    meetings = services.get_project_meetings(db, current_user.company_id, project_id, broker_id, sales_user_id)
    response = []
    for m in meetings:
        response.append(_meeting_response(m, db))
    return response

@router.post("/meetings", response_model=MeetingResponse, summary="Crear o Agendar Cita")
def schedule_meeting(
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES]))
):
    assigned_sales_user_id = current_user.id if current_user.role == UserRole.SALES else None
    meeting = services.create_meeting(db, payload, current_user.company_id, assigned_sales_user_id)
    return _meeting_response(meeting, db)

@router.put("/meetings/{meeting_id}", response_model=MeetingResponse, summary="Actualizar cita y broker")
def update_meeting(
    meeting_id: str,
    payload: MeetingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES])),
):
    meeting = services.update_meeting(
        db, meeting_id, current_user.company_id, payload,
        current_user.id if current_user.role == UserRole.SALES else None,
    )
    return _meeting_response(meeting, db)


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    services.delete_meeting(db, meeting_id, current_user.company_id)


@router.get("/availability/me", response_model=List[AvailabilityWindowResponse])
def get_my_availability(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.availability_for_user(db, current_user.id)


@router.put("/availability/me", response_model=List[AvailabilityWindowResponse])
def set_my_availability(
    payload: AvailabilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.replace_availability(
        db,
        user=current_user,
        timezone_name=payload.timezone,
        windows=[item.model_dump() for item in payload.windows],
    )


@router.get("/availability-blocks/me", response_model=List[AvailabilityBlockResponse])
def get_my_availability_blocks(
    start: datetime,
    end: datetime,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.availability_blocks_for_user(
        db, user_id=current_user.id, starts_at=start, ends_at=end,
    )


@router.post("/availability-blocks/me", response_model=AvailabilityBlockResponse, status_code=status.HTTP_201_CREATED)
def add_my_availability_block(
    payload: AvailabilityBlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.create_availability_block(
        db, user=current_user, starts_at=payload.starts_at, ends_at=payload.ends_at,
        timezone_name=payload.timezone,
    )


@router.put("/availability-blocks/me/{block_id}", response_model=AvailabilityBlockResponse)
def edit_my_availability_block(
    block_id: str,
    payload: AvailabilityBlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.update_availability_block(
        db, user=current_user, block_id=block_id, starts_at=payload.starts_at,
        ends_at=payload.ends_at, timezone_name=payload.timezone,
    )


@router.delete("/availability-blocks/me/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_availability_block(
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    scheduling.delete_availability_block(db, user_id=current_user.id, block_id=block_id)


def _company_sales_user(db: Session, company_id: str, user_id: str) -> User:
    user = db.query(User).filter(
        User.id == user_id, User.company_id == company_id, User.role == UserRole.SALES,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Sales user not found.")
    return user


@router.post("/availability-blocks/{sales_user_id}", response_model=AvailabilityBlockResponse, status_code=status.HTTP_201_CREATED)
def add_sales_user_availability_block(
    sales_user_id: str,
    payload: AvailabilityBlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    """Administrator/Assistant master control. Overlap checks remain per Sales user."""
    sales_user = _company_sales_user(db, current_user.company_id, sales_user_id)
    return scheduling.create_availability_block(
        db, user=sales_user, starts_at=payload.starts_at, ends_at=payload.ends_at,
        timezone_name=payload.timezone,
    )


@router.put("/availability-blocks/{sales_user_id}/{block_id}", response_model=AvailabilityBlockResponse)
def edit_sales_user_availability_block(
    sales_user_id: str,
    block_id: str,
    payload: AvailabilityBlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    sales_user = _company_sales_user(db, current_user.company_id, sales_user_id)
    return scheduling.update_availability_block(
        db, user=sales_user, block_id=block_id, starts_at=payload.starts_at,
        ends_at=payload.ends_at, timezone_name=payload.timezone,
    )


@router.delete("/availability-blocks/{sales_user_id}/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_sales_user_availability_block(
    sales_user_id: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _company_sales_user(db, current_user.company_id, sales_user_id)
    scheduling.delete_availability_block(db, user_id=sales_user_id, block_id=block_id)


@router.get("/schedule/me", response_model=SalesScheduleResponse)
def get_my_schedule(
    start: datetime,
    end: datetime,
    project_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    start_value = start.astimezone(timezone.utc).replace(tzinfo=None) if start.tzinfo else start
    end_value = end.astimezone(timezone.utc).replace(tzinfo=None) if end.tzinfo else end
    meetings_query = db.query(Meeting).join(Project, Project.id == Meeting.project_id).filter(
        Meeting.assigned_sales_user_id == current_user.id,
        Project.company_id == current_user.company_id,
        Meeting.meeting_time >= start_value,
        Meeting.meeting_time < end_value,
    )
    if project_id:
        meetings_query = meetings_query.filter(Meeting.project_id == project_id)
    meetings = meetings_query.order_by(Meeting.meeting_time).all()
    meeting_rows = []
    for meeting in meetings:
        meeting_rows.append(_meeting_response(meeting, db))
    return {
        "availability": scheduling.availability_blocks_for_user(
            db, user_id=current_user.id, starts_at=start, ends_at=end,
        ),
        "meetings": meeting_rows,
    }


@router.get("/schedule", response_model=ManagerSalesScheduleResponse)
def get_company_sales_schedule(
    start: datetime,
    end: datetime,
    sales_user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
    project_id: Optional[str] = None,
):
    sales_query = db.query(User).filter(
        User.company_id == current_user.company_id, User.role == UserRole.SALES, User.is_active.is_(True),
    ).order_by(User.first_name, User.last_name, User.email)
    sales_users = sales_query.all()
    allowed_ids = {user.id for user in sales_users}
    if sales_user_id and sales_user_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Sales user not found.")
    selected_ids = {sales_user_id} if sales_user_id else allowed_ids
    start_value = start.astimezone(timezone.utc).replace(tzinfo=None) if start.tzinfo else start
    end_value = end.astimezone(timezone.utc).replace(tzinfo=None) if end.tzinfo else end
    meetings_query = db.query(Meeting).join(Project, Project.id == Meeting.project_id).filter(
        Project.company_id == current_user.company_id,
        Meeting.assigned_sales_user_id.in_(selected_ids),
        Meeting.meeting_time >= start_value,
        Meeting.meeting_time < end_value,
    )
    if project_id:
        if not db.query(Project.id).filter(Project.id == project_id, Project.company_id == current_user.company_id).first():
            raise HTTPException(status_code=404, detail="Project not found.")
        meetings_query = meetings_query.filter(Meeting.project_id == project_id)
    meetings = [] if not selected_ids else meetings_query.order_by(Meeting.meeting_time).all()
    blocks = [] if not selected_ids else db.query(SalesAvailabilityBlock).filter(
        SalesAvailabilityBlock.user_id.in_(selected_ids),
        SalesAvailabilityBlock.ends_at > start_value,
        SalesAvailabilityBlock.starts_at < end_value,
    ).order_by(SalesAvailabilityBlock.starts_at).all()
    names = {user.id: " ".join(filter(None, [user.first_name, user.last_name])) or user.email for user in sales_users}
    availability = []
    for block in blocks:
        item = AvailabilityBlockResponse.model_validate(block)
        item.sales_user_name = names.get(block.user_id)
        availability.append(item)
    return {
        "sales_users": sales_users,
        "availability": availability,
        "meetings": [_meeting_response(meeting, db) for meeting in meetings],
    }


@router.post("/meetings/{meeting_id}/attachments", response_model=MeetingAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_meeting_attachment(
    meeting_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES])),
):
    meeting = services.get_tenant_meeting(
        db, meeting_id, current_user.company_id,
        current_user.id if current_user.role == UserRole.SALES else None,
    )
    reportable_statuses = {
        MeetingStatus.IN_PROGRESS, MeetingStatus.COMPLETED, MeetingStatus.COMPLETED_SALE_PENDING, MeetingStatus.SALE_CLOSED,
    }
    if meeting.status not in reportable_statuses:
        raise HTTPException(status_code=409, detail="Start the visit before uploading report attachments.")
    rule = ATTACHMENT_RULES.get(kind)
    content_type = (file.content_type or "").lower()
    if not rule or content_type not in rule[0]:
        raise HTTPException(status_code=422, detail="Unsupported attachment type.")
    content = await file.read(rule[1] + 1)
    if not content or len(content) > rule[1]:
        raise HTTPException(status_code=413, detail="Attachment is empty or exceeds the size limit.")
    attachment_id = str(uuid.uuid4())
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}[content_type]
    stored = storage_service.store_meeting_attachment(
        company_id=current_user.company_id, meeting_id=meeting.id, attachment_id=attachment_id,
        extension=extension, content=content,
    )
    attachment = MeetingAttachment(
        id=attachment_id, meeting_id=meeting.id, uploaded_by_user_id=current_user.id, kind=kind,
        storage_path=stored.relative_path, original_filename=Path(file.filename or f"attachment{extension}").name[:255],
        mime_type=content_type, size_bytes=len(content),
    )
    db.add(attachment); db.commit(); db.refresh(attachment)
    return MeetingAttachmentResponse.model_validate(attachment).model_copy(update={
        "download_url": f"/api/v1/sales/meetings/{meeting.id}/attachments/{attachment.id}",
    })


@router.get("/meetings/{meeting_id}/attachments/{attachment_id}")
def download_meeting_attachment(
    meeting_id: str,
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES])),
):
    services.get_tenant_meeting(
        db, meeting_id, current_user.company_id,
        current_user.id if current_user.role == UserRole.SALES else None,
    )
    attachment = db.query(MeetingAttachment).filter(
        MeetingAttachment.id == attachment_id, MeetingAttachment.meeting_id == meeting_id,
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    try:
        path = storage_service.resolve_meeting_attachment(attachment.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return FileResponse(
        path, media_type=attachment.mime_type, filename=attachment.original_filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/calendar-connections/me", response_model=List[CalendarConnectionResponse])
def get_my_calendar_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.calendar_connections_for_user(db, current_user.id)


@router.put("/calendar-connections/me", response_model=CalendarConnectionResponse)
def set_my_calendar_connection(
    payload: CalendarConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SALES])),
):
    return scheduling.upsert_calendar_connection(
        db,
        user_id=current_user.id,
        provider=payload.provider,
        calendar_id=payload.calendar_id,
    )

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
