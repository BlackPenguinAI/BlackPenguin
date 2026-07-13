from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import httpx  
import re # 🚀 IMPORTANTE: Para detectar URLs en el texto del chat

from app.core.config import settings
from app.db.postgres import get_db

# 1. Modelos de Base de Datos
from app.modules.tenants.models import (
    Company, 
    SubscriptionPlan,
    OnboardingProtocol,     
    OnboardingSession,      
    OnboardingMessage,      
    CompanyProfile,         
    SenderType
)
from app.modules.properties.models import Project 
from app.modules.auth.models import User, UserRole
from app.modules.sales.models import WaitlistEmail 

# 2. Esquemas de validación
from app.modules.tenants.schemas import (
    CompanyCreate, CompanyUpdate, CompanyResponse,
    SubscriptionPlanCreate, SubscriptionPlanUpdate, SubscriptionPlanResponse,
    DeveloperCreate, DeveloperUpdate, DeveloperResponse,
    ChatMessagePayload, ChatMessageResponse, OnboardingSessionStatus,
    CompanyProfileUpdate, CompanyProfileResponse    
)

# 3. Tareas en segundo plano (Web Scraping Maestro)
from app.modules.tenants.scraper import scrape_and_enrich_profile

# 4. Dependencias
from app.modules.auth.deps import RoleChecker, get_current_user
from datetime import timedelta
from app.core.security import create_email_token, get_password_hash
from app.core.email import send_email

router = APIRouter()

# =========================================================
# 📊 DASHBOARD: ESTADÍSTICAS GLOBALES
# =========================================================
@router.get("/stats", summary="Estadísticas globales para el Dashboard")
def get_global_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return {
        "total_companies": db.query(Company).count(),
        "active_companies": db.query(Company).filter(Company.is_active == True).count(),
        "total_projects": db.query(Project).count(),
        "total_waitlist": db.query(WaitlistEmail).count(),
        "total_users": db.query(User).count(),
        "system_status": "Operational"
    }

# =========================================================
# 💳 CRUD DE PLANES DE SUSCRIPCIÓN
# =========================================================
@router.get("/plans", response_model=List[SubscriptionPlanResponse], summary="Listar Planes")
def get_plans(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return db.query(SubscriptionPlan).order_by(SubscriptionPlan.name.asc()).all()

@router.post("/plans", response_model=SubscriptionPlanResponse, summary="Crear Plan")
def create_plan(payload: SubscriptionPlanCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    new_plan = SubscriptionPlan(**payload.model_dump())
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return new_plan

@router.put("/plans/{plan_id}", response_model=SubscriptionPlanResponse, summary="Actualizar Plan")
def update_plan(plan_id: str, payload: SubscriptionPlanUpdate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)
        
    db.commit()
    db.refresh(plan)
    return plan

@router.delete("/plans/{plan_id}", summary="Eliminar Plan")
def delete_plan(plan_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    
    empresas_activas = db.query(Company).filter(Company.plan_id == plan_id).count()
    if empresas_activas > 0:
        raise HTTPException(status_code=400, detail="No se puede eliminar: hay empresas usando este plan.")
        
    db.delete(plan)
    db.commit()
    return {"message": "Plan eliminado con éxito"}

# =========================================================
# 🏢 CRUD DE EMPRESAS (TENANTS)
# =========================================================
@router.get("/", response_model=List[CompanyResponse], summary="Listar Empresas (Developers)")
def get_companies(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return db.query(Company).order_by(Company.license_start.desc()).all()

@router.post("/", response_model=CompanyResponse, summary="Crear Nueva Empresa")
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    new_company = Company(**payload.model_dump())
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    return new_company

@router.put("/{company_id}", response_model=CompanyResponse, summary="Actualizar Empresa")
def update_company(company_id: str, payload: CompanyUpdate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(company, key, value)
        
    db.commit()
    db.refresh(company)
    return company

@router.delete("/{company_id}", summary="Eliminar Empresa")
def delete_company(company_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
    db.delete(company)
    db.commit()
    return {"message": "Empresa eliminada con éxito"}

# =========================================================
# 🏢 CRUD DE DESARROLLADORES (ONBOARDING MAESTRO)
# =========================================================
@router.get("/developers", response_model=List[DeveloperResponse], summary="Listar Developers")
def get_developers(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    companies = db.query(Company).order_by(Company.license_start.desc()).all()
    results = []
    
    for company in companies:
        admin = db.query(User).filter(User.company_id == company.id, User.role == UserRole.ADMIN).first()
        
        first_name_clean = ""
        paternal_clean = ""
        maternal_clean = ""
        
        if admin:
            if admin.last_name_paternal or admin.last_name_maternal:
                first_name_clean = admin.full_name if admin.full_name else ""
                if admin.last_name_paternal and first_name_clean:
                    first_name_clean = first_name_clean.replace(admin.last_name_paternal, "").strip()
                if admin.last_name_maternal and first_name_clean:
                    first_name_clean = first_name_clean.replace(admin.last_name_maternal, "").strip()
                
                paternal_clean = admin.last_name_paternal or ""
                maternal_clean = admin.last_name_maternal or ""
            else:
                parts = admin.full_name.split(' ') if admin.full_name else []
                if len(parts) > 0: first_name_clean = parts[0]
                if len(parts) > 1: paternal_clean = parts[1]
                if len(parts) > 2: maternal_clean = ' '.join(parts[2:])

        dev_data = {
            "id": company.id,
            "name": company.name, 
            "license_start": company.license_start,
            "license_end": company.license_end,
            "plan_duration_months": company.plan_duration_months,
            "is_active": company.is_active,
            "payment_receipt_url": company.payment_receipt_url,
            "plan_id": company.plan_id,
            "admin_email": admin.email if admin else "",
            "admin_first_name": first_name_clean,
            "admin_paternal_last_name": paternal_clean,
            "admin_maternal_last_name": maternal_clean
        }
        results.append(dev_data)
        
    return results

@router.post("/developers", response_model=DeveloperResponse, status_code=status.HTTP_201_CREATED, summary="Registrar Nuevo Desarrollador")
def create_developer(
    payload: DeveloperCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    from datetime import datetime, timedelta
    import uuid

    existing_user = db.query(User).filter(User.email == payload.admin_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="El correo del administrador ya está en uso.")
    
    start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=30 * payload.duration_months)
    
    new_company = Company(
        name=payload.company_name,
        plan_id=payload.plan_id,
        license_start=start_date,
        plan_duration_months=payload.duration_months,
        license_end=end_date,
        is_active=payload.is_active
    )
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    
    new_profile = CompanyProfile(
        company_id=new_company.id, 
        scraped_source_url=payload.website_url
    )
    db.add(new_profile)
    db.commit()

    # 🚀 SI INGRESARON URL EN EL MODAL, SE ACTIVA EL SCRAPER EN SEGUNDO PLANO
    if payload.website_url:
        background_tasks.add_task(scrape_and_enrich_profile, new_company.id, payload.website_url)

    full_name_compiled = f"{payload.admin_first_name} {payload.admin_paternal_last_name} {payload.admin_maternal_last_name}".strip()

    new_user = User(
        email=payload.admin_email,
        full_name=full_name_compiled,
        last_name_paternal=payload.admin_paternal_last_name,
        last_name_maternal=payload.admin_maternal_last_name,
        hashed_password=get_password_hash(str(uuid.uuid4())), 
        role=UserRole.ADMIN,
        company_id=new_company.id,
        is_active=True
    )
    db.add(new_user)
    db.commit()

    token = create_email_token(payload.admin_email, new_user.hashed_password)
    activation_link = f"http://localhost:4200/set-password?token={token}"
    
    comp_name = payload.company_name
    saludo_name = f"{payload.admin_first_name} {payload.admin_paternal_last_name}"

    if payload.language == "es":
        subject = "Activación de Cuenta - Black Penguin"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #111; color: white; border-radius: 10px;">
            <h2 style="color: #facc15;">Bienvenido a Black Penguin, {saludo_name}</h2>
            <p>Su empresa <b>{comp_name}</b> ha sido habilitada exitosamente en nuestro ecosistema.</p>
            <p>Para activar su cuenta administrativa y configurar su clave de acceso, haga clic en el botón inferior:</p>
            <br>
            <a href="{activation_link}" style="display: inline-block; padding: 12px 24px; background-color: #facc15; color: black; font-weight: bold; text-decoration: none; border-radius: 6px;">Activar Mi Cuenta</a>
        </div>
        """
    else:
        subject = "Account Activation - Black Penguin"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #111; color: white; border-radius: 10px;">
            <h2 style="color: #facc15;">Welcome to Black Penguin, {saludo_name}</h2>
            <p>Your company <b>{comp_name}</b> has been successfully provisioned in our real estate ecosystem.</p>
            <p>To activate your account and set up your access password, please click below:</p>
            <br>
            <a href="{activation_link}" style="display: inline-block; padding: 12px 24px; background-color: #facc15; color: black; font-weight: bold; text-decoration: none; border-radius: 6px;">Activate My Account</a>
        </div>
        """
    
    send_email(payload.admin_email, subject, html_content)
    return new_company

@router.post("/developers/{company_id}/resend-activation", summary="Re-enviar link de recuperación/activación")
def resend_activation_link(company_id: str, lang: str = "en", db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    admin_user = db.query(User).filter(User.company_id == company_id, User.role == UserRole.ADMIN).first()
    if not admin_user:
        raise HTTPException(status_code=404, detail="No se encontró un administrador para esta empresa.")
        
    token = create_email_token(admin_user.email, admin_user.hashed_password)
    activation_link = f"http://localhost:4200/set-password?token={token}"
    
    if lang == "es":
        subject = "Recuperación de Acceso - Black Penguin"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #111; color: white; border-radius: 10px;">
            <h2 style="color: #facc15;">Recuperación de Acceso</h2>
            <p>Hemos recibido una solicitud para restablecer o activar su acceso en Black Penguin.</p>
            <a href="{activation_link}" style="display: inline-block; padding: 12px 24px; background-color: #facc15; color: black; font-weight: bold; text-decoration: none; border-radius: 6px;">Restablecer Contraseña</a>
        </div>
        """
    else:
        subject = "Access Recovery - Black Penguin"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #111; color: white; border-radius: 10px;">
            <h2 style="color: #facc15;">Access Recovery</h2>
            <p>We received a request to reset or activate your Black Penguin access.</p>
            <a href="{activation_link}" style="display: inline-block; padding: 12px 24px; background-color: #facc15; color: black; font-weight: bold; text-decoration: none; border-radius: 6px;">Reset Password</a>
        </div>
        """
        
    send_email(admin_user.email, subject, html_content)
    return {"message": "Correo enviado con éxito."}

@router.put("/developers/{company_id}", response_model=DeveloperResponse, summary="Actualizar Desarrollador")
def update_developer(company_id: str, payload: DeveloperUpdate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    update_data = payload.model_dump(exclude_unset=True)
    
    if "company_name" in update_data and update_data["company_name"] is not None:
        company.name = update_data["company_name"]
    for key in ["plan_id", "duration_months", "is_active", "payment_receipt_url"]:
        if key in update_data:
            setattr(company, key, update_data[key])
            
    if "duration_months" in update_data:
        from datetime import datetime, timedelta
        company.license_end = company.license_start + timedelta(days=30 * update_data["duration_months"])
        
    admin_user = db.query(User).filter(User.company_id == company_id, User.role == UserRole.ADMIN).first()
    if admin_user:
        if "admin_email" in update_data and update_data["admin_email"] != admin_user.email:
            existing_email = db.query(User).filter(User.email == update_data["admin_email"]).first()
            if existing_email:
                raise HTTPException(status_code=400, detail="El correo del administrador ya está en uso.")
            admin_user.email = update_data["admin_email"]
            
        if "admin_first_name" in update_data or "admin_paternal_last_name" in update_data or "admin_maternal_last_name" in update_data:
            fn = update_data.get("admin_first_name") or admin_user.full_name.split(' ')[0] if admin_user.full_name else ""
            ap = update_data.get("admin_paternal_last_name") or admin_user.last_name_paternal or ""
            am = update_data.get("admin_maternal_last_name") or admin_user.last_name_maternal or ""
            
            if "admin_first_name" in update_data: admin_user.full_name = update_data["admin_first_name"]
            if "admin_paternal_last_name" in update_data: admin_user.last_name_paternal = update_data["admin_paternal_last_name"]
            if "admin_maternal_last_name" in update_data: admin_user.last_name_maternal = update_data["admin_maternal_last_name"]
            
            admin_user.full_name = f"{fn} {ap} {am}".strip()

    db.commit()
    db.refresh(company)
    return company

@router.delete("/developers/{company_id}", summary="Eliminar Desarrollador")
def delete_developer(company_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
    db.delete(company)
    db.commit()
    return {"message": "Empresa y todos sus proyectos/usuarios eliminados con éxito"}


# =========================================================================
# ⚙️ ENTORNO CLIENTE: ENDPOINTS DEL PERFIL COGNITIVO (tracker del UI)
# =========================================================================
@router.get("/onboarding/profile", response_model=CompanyProfileResponse, summary="Obtener el Perfil de la Empresa")
def get_company_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa vinculada.")
        
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == current_user.company_id).first()
    if not profile:
        profile = CompanyProfile(company_id=current_user.company_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        
    return profile

@router.put("/onboarding/profile", response_model=CompanyProfileResponse, summary="Actualizar Perfil (Por IA o Manual)")
def update_company_profile(payload: CompanyProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa vinculada.")
        
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == current_user.company_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil no encontrado.")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)

    profile.is_identity_completed = bool(profile.legal_name and profile.headquarters)
    profile.is_team_completed = bool(len(profile.executive_team) > 0)
    profile.is_focus_completed = bool(len(profile.asset_classes) > 0)
    profile.is_market_completed = bool(profile.market_coverage)
    profile.is_strategy_completed = bool(profile.investment_strategy)
    profile.is_value_prop_completed = bool(profile.value_proposition)
    profile.is_brand_completed = bool(profile.tone_of_voice and profile.key_messaging)

    profile.is_profile_fully_completed = all([
        profile.is_identity_completed, profile.is_team_completed, profile.is_focus_completed, 
        profile.is_market_completed, profile.is_strategy_completed, profile.is_value_prop_completed, 
        profile.is_brand_completed
    ])

    db.commit()
    db.refresh(profile)
    return profile


# =========================================================
# 🧠 ENTORNO CLIENTE: CHAT DE COMPANY ONBOARDING CON MAGIA
# =========================================================
@router.get("/onboarding/session", response_model=OnboardingSessionStatus, summary="Obtener o iniciar sesión de chat")
def get_or_create_onboarding_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="El usuario no pertenece a ninguna empresa desarrolladora.")

    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == current_user.company_id).first()
    
    if not session:
        session = OnboardingSession(company_id=current_user.company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
        
        welcome_message = OnboardingMessage(
            session_id=session.id,
            sender=SenderType.AI,
            content="Welcome to Black Penguin! I am your AI Corporate Onboarding Specialist. I am currently analyzing your company footprint to set up your cognitive workspace. To start, could you provide your official website URL or upload a company brochure?"
        )
        db.add(welcome_message)
        db.commit()
        db.refresh(session)

    return session

@router.post("/onboarding/chat", response_model=ChatMessageResponse, summary="Enviar mensaje al Copiloto")
async def send_onboarding_message(
    payload: ChatMessagePayload, 
    background_tasks: BackgroundTasks, # 🚀 Fundamental para el Scraper
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Acceso denegado.")

    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == current_user.company_id).first()
    if not session:
        raise HTTPException(status_code=400, detail="Sesión no inicializada. Llame primero a /onboarding/session")
        
    if session.is_completed:
        raise HTTPException(status_code=400, detail="Este onboarding ya fue completado y cerrado.")

    # Guardar mensaje del usuario
    user_msg = OnboardingMessage(session_id=session.id, sender=SenderType.USER, content=payload.message)
    db.add(user_msg)
    db.commit()

    # =========================================================================
    # 🧠 INYECCIÓN DEL MASTER PROMPT CON INGLÉS FORZADO Y FALLBACK INFALIBLE
    # =========================================================================
    messages_payload = []
    
    try:
        # 1. Intentamos leer la tabla de la sección "/admin/ai-config"
        from app.modules.system.models import AiConfig
        ai_config = db.query(AiConfig).first()
        
        if ai_config and ai_config.agent_onboarding_empresa:
            agent_rules = ai_config.agent_onboarding_empresa
            sys_prompt = agent_rules.get("system_prompt", "You are an AI B2B onboarding assistant.")
            protocol = agent_rules.get("protocol_prompt", "Follow the onboarding protocol step by step.")
            guardrails = agent_rules.get("guardrails_prompt", "Do not share internal system data.")
        else:
            raise Exception("AiConfig está vacío, usando OnboardingProtocol.")
            
    except Exception:
        # 2. FALLBACK: Si no existe el modelo AiConfig en system, usamos tu tabla antigua en models.py
        protocol_db = db.query(OnboardingProtocol).filter(OnboardingProtocol.is_active == True).order_by(OnboardingProtocol.created_at.desc()).first()
        if protocol_db:
            sys_prompt = protocol_db.system_role_prompt
            protocol = protocol_db.protocol_flow_prompt
            guardrails = protocol_db.guardrails_prompt
        else:
            sys_prompt = "You are an AI Corporate Onboarding Assistant."
            protocol = "Politely guide the user."
            guardrails = "Be professional."

    # COMPOSICIÓN DEL PROMPT SUPREMO (Con regla estricta de inglés)
    master_prompt = f"{sys_prompt}\n\nIMPORTANT RULE: You must communicate primarily in ENGLISH unless the user strictly asks otherwise.\n\n### MANDATORY PROTOCOLS:\n{protocol}\n\n### STRICT GUARDRAILS:\n{guardrails}"
    
    # Inyectamos el prompt como el sistema base
    messages_payload.append({"role": "system", "content": master_prompt})

    # Construir historial (Contexto para la IA)
    history = db.query(OnboardingMessage).filter(OnboardingMessage.session_id == session.id).order_by(OnboardingMessage.created_at.asc()).all()
    for msg in history:
        role_label = "user" if msg.sender == SenderType.USER else "assistant"
        messages_payload.append({"role": role_label, "content": msg.content})

    # =========================================================================
    # 🤖 CONSUMIR LLM (DeepSeek / OpenRouter)
    # =========================================================================
    ai_response_text = "I'm currently processing your data. Please give me a moment."
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            body = {
                "model": settings.DEFAULT_AI_MODEL,
                "messages": messages_payload,
                "temperature": 0.3 # Bajo para respuestas asertivas y corporativas
            }
            
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers, timeout=30.0)
            
            if response.status_code == 200:
                resp_json = response.json()
                ai_response_text = resp_json["choices"][0]["message"]["content"]
            else:
                print(f"❌ OpenRouter rechazó la petición. Status: {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error conectando al LLM: {e}")

    # Guardar respuesta IA
    ai_msg = OnboardingMessage(session_id=session.id, sender=SenderType.AI, content=ai_response_text)
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    # =========================================================================
    # ✨ WOW EFFECT: DISPARAR EL SCRAPER SI EL USUARIO MANDA UNA WEB
    # =========================================================================
    urls = re.findall(r'(https?://[^\s]+)', payload.message)
    if urls:
        first_url = urls[0]
        # El scraping correrá por detrás en segundo plano sin congelar el endpoint
        background_tasks.add_task(scrape_and_enrich_profile, current_user.company_id, first_url)

    return ai_msg

# =========================================================================
# 📥 DESCARGAR HISTORIAL DEL CHAT (GET)
# =========================================================================
@router.get("/onboarding/chat", response_model=List[ChatMessageResponse], summary="Obtener historial del chat actual")
def get_chat_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. Validar que el usuario tenga empresa
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa vinculada.")

    # 2. Buscar la sesión activa de Onboarding
    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == current_user.company_id).first()
    
    # 3. Si no hay sesión, devolvemos una lista vacía
    if not session:
        return []

    # 4. Extraer los mensajes ordenados por fecha de creación
    history = db.query(OnboardingMessage).filter(OnboardingMessage.session_id == session.id).order_by(OnboardingMessage.created_at.asc()).all()
    
    # 5. Formatear la respuesta para que empate con la interfaz (Angular)
    formatted_history = []
    for msg in history:
        # Transformar SenderType (ENUM) en el string esperado por el UI ('user' o 'ai')
        sender_label = "user" if msg.sender == SenderType.USER else "ai"
        
        formatted_history.append({
            "sender": sender_label,
            "content": msg.content,
            "created_at": msg.created_at
        })

    return formatted_history