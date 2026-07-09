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
from app.core.email import send_email

router = APIRouter()

# =================================================================
# 🚀 ENDPOINTS: LISTA DE ESPERA (POSTGRESQL NATIVO)
# =================================================================
class WaitlistRequest(BaseModel):
    email: EmailStr
    language: str = "en" # 🚀 NUEVO: Recibimos el idioma desde el Landing Page

class WaitlistResponse(BaseModel):
    id: str
    email: str
    created_at: datetime
    class Config:
        from_attributes = True

@router.post("/waitlist", summary="Unirse a la lista de espera")
def join_waitlist(payload: WaitlistRequest, db: Session = Depends(get_db)):
    # 1. Validar si el correo ya existe
    existing_email = db.query(WaitlistEmail).filter(WaitlistEmail.email == payload.email).first()
    if existing_email:
        error_msg = "Este correo ya se encuentra en la lista de espera." if payload.language == 'es' else "This email is already on the waitlist."
        raise HTTPException(status_code=400, detail=error_msg)
    
    # 2. Guardar en Base de Datos
    new_email = WaitlistEmail(email=payload.email)
    db.add(new_email)
    db.commit()

    # 3. 🚀 PREPARAR EL CONTENIDO DEL CORREO SEGÚN EL IDIOMA
    if payload.language == 'es':
        subject = "¡Bienvenido a la Lista de Espera! | Black Penguin"
        title = "Estás en la lista"
        message = "Gracias por unirte a la lista de espera de <strong>Black Penguin</strong>. Estamos preparando todo para revolucionar el desarrollo inmobiliario con Inteligencia Artificial. Te notificaremos tan pronto como abramos nuevos cupos para el onboarding."
        footer = "El equipo de Black Penguin"
        success_msg = "Suscripción exitosa"
    else:
        subject = "Welcome to the Waitlist! | Black Penguin"
        title = "You're on the list"
        message = "Thank you for joining the <strong>Black Penguin</strong> waitlist. We are preparing everything to revolutionize real estate development with Artificial Intelligence. We will notify you as soon as we open new spots for onboarding."
        footer = "The Black Penguin Team"
        success_msg = "Successfully subscribed"

    # 4. 🚀 PLANTILLA HTML CORPORATIVA (Estilo Liquid Glass oscuro)
    html_content = f"""
    <div style="background-color: #000000; color: #ffffff; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; padding: 50px 20px; text-align: center;">
        <div style="max-width: 500px; margin: 0 auto; background-color: #111111; border: 1px solid rgba(255,255,255,0.1); border-radius: 24px; padding: 40px 30px; box-shadow: 0 0 40px rgba(234, 179, 8, 0.05);">
            <div style="margin-bottom: 24px;">
                <span style="font-size: 24px; font-weight: 600; color: #ffffff; letter-spacing: -0.5px;">Black</span><span style="font-size: 24px; font-weight: 300; color: #EAB308; letter-spacing: -0.5px;">Penguin</span>
            </div>
            <h2 style="font-size: 22px; font-weight: 300; margin-bottom: 16px; color: #ffffff;">{title}</h2>
            <p style="font-size: 15px; color: #9ca3af; line-height: 1.6; margin-bottom: 32px;">
                {message}
            </p>
            <div style="border-top: 1px solid rgba(255,255,255,0.05); padding-top: 24px; margin-top: 24px;">
                <p style="font-size: 12px; color: #6b7280;">{footer}<br>© 2026 Black Penguin AI. All rights reserved.</p>
            </div>
        </div>
    </div>
    """

    # 5. 🚀 ENVIAR CORREO (Protegido con Try/Except para no romper el registro si falla el SMTP)
    try:
        send_email(
            to_email=payload.email,
            subject=subject,
            html_content=html_content
        )
    except Exception as e:
        print(f"⚠️ Error enviando correo de confirmación a {payload.email}: {e}")

    return {"message": success_msg}

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