import os
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified 

from app.db.base import Base
from app.db.postgres import engine, SessionLocal
from app.core.security import get_password_hash

# 🚀 IMPORTACIONES DE MODELOS
from app.modules.users.models import User, UserRole
from app.modules.ai_core.models import AIConfiguration 
from app.modules.system_settings.models import FirebaseConfig, TwilioConfig
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.companies.models import Company # Asegúrate de importar esto para que lo reconozca

def init_db():
    print("🛑 ATENCIÓN: MODO 'CLEAN SLATE' ACTIVADO")
    print("🗑️ Destruyendo tablas deprecadas...")
    Base.metadata.drop_all(bind=engine)
    
    print("✨ Reconstruyendo base de datos desde cero...")
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        # =======================================================
        # 🔧 0. PARCHE REPARADOR DE COLUMNA FALTANTE
        # =======================================================
        print("🔧 Asegurando columnas faltantes en PostgreSQL...")
        db.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
        db.commit()
        print("✅ Columna 'created_at' asegurada en la tabla companies.")

        # =======================================================
        # 👑 1. SEMBRAR SUPERADMIN
        # =======================================================
        sa_email = os.getenv("FIRST_SUPERADMIN_EMAIL", "superadmin@blackpenguin.ai")
        sa_pass = os.getenv("FIRST_SUPERADMIN_PASSWORD", "sa1234")

        existing_sa = db.query(User).filter(User.email == sa_email).first()
        if not existing_sa:
            print(f"🌱 Sembrando Superadmin por defecto: {sa_email}")
            superadmin = User(
                email=sa_email,
                hashed_password=get_password_hash(sa_pass),
                role=UserRole.SUPERADMIN,
                is_active=True
            )
            db.add(superadmin)
            db.commit()
        else:
            print("✅ El Superadmin ya existe.")

        # =======================================================
        # 🧠 2. SEMBRAR AI KEYS & AI CONFIG (Multi-Agente)
        # =======================================================
        print("🤖 Sembrando Inteligencia Artificial (Prompts & Keys)...")
        ai_config = db.query(AIConfiguration).filter(AIConfiguration.company_id == None).first()
        if not ai_config:
            ai_config = AIConfiguration()
            db.add(ai_config)

        ai_config.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-PON_TU_LLAVE_REAL_AQUI")
        ai_config.available_models = ["openai/gpt-4o-mini", "openai/gpt-4o", "anthropic/claude-3-5-sonnet"]

        # --- A. PROMPTS DE LA EMPRESA ---
        ai_config.agent_onboarding_empresa = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """You are the Elite Corporate Onboarding Specialist for Black Penguin, a premium AI SaaS for Real Estate Developers. \n\nYour mission is to extract, validate, and structure the official "Company Profile" based on the Black Penguin USA Real Estate Developer Client Record. You are conversing with a high-level executive (Admin) of a Real Estate Development firm.\n\nYour tone must be highly professional, consultative, proactive, and efficient. You do not wait for the client to do all the work; you propose, summarize, and confirm. \n\nThe essential data points you must gather to complete the onboarding are:\n1. Company Identity (Legal Name, DBA, Headquarters, Year Established).\n2. Executive Team & Key Contacts.\n3. Core Focus & Asset Classes (e.g., Multi-family, Commercial, Mixed-use).\n4. Market Coverage & Target Demographics.\n5. Investment Strategy & Portfolio Size (AUM).\n6. Value Proposition & Key Differentiators.\n7. Brand Guidelines (Tone of voice, key messaging).\n\nYou have access to a background system that parses website URLs and uploaded documents (PDFs, DOCX).""",
            "protocol_prompt": """Follow these sequential steps to ensure a frictionless "Wow Effect" onboarding:\n\nSTEP 1: PROACTIVE GREETING & SCRAPED DATA PRESENTATION\nIf the system provides you with data scraped from the client's registered website URL, start the conversation by warmly welcoming them and presenting a concise summary of what you have already learned about their company.\n\nSTEP 2: GAP ANALYSIS & MULTI-MODAL DATA GATHERING\nCross-reference the confirmed data with the 7 essential data points from your System Role. Identify exactly what is missing.\n\nSTEP 3: ITERATIVE CONFIRMATION & REAL-TIME UI SYNC\nEvery time the client provides new information (via text, URL, or file), immediately acknowledge it, summarize the extracted data, and explicitly state that you are saving it to their profile.\n\nSTEP 4: ONBOARDING COMPLETION & HANDOFF\nOnce all 7 essential data points are collected and validated, congratulate the client.""",
            "guardrails_prompt": """1. NO DATA HALLUCINATION: If a field is missing, ask for it. Never invent company history, financial figures, or brand guidelines.\n2. CONCISENESS: Real estate executives are busy. Keep your responses under 150 words unless summarizing large data dumps.\n3. STRICT SCOPE: This agent handles ONLY the "Company" profile.\n4. FILE PROCESSING AWARENESS: If the user uploads a file or shares a URL, explicitly acknowledge receipt.\n5. PROGRESSIVE OVERLOAD AVOIDANCE: Never ask more than two questions at the same time."""
        }

        # --- B. PROMPTS DEL PROYECTO (3 PILARES) ---
        ai_config.agent_onboarding_proyectos = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """Eres el Arquitecto de Datos Inmobiliarios IA de Black Penguin. Tu misión es extraer, procesar y estructurar meticulosamente los detalles técnicos, comerciales y de inventario de los proyectos autorizados del desarrollador. Tienes un perfil altamente analítico. Comprendes perfectamente términos como "tipologías", "amenidades", "inventario disponible", "ROI" y "etapas de entrega".""",
            "protocol_prompt": """1. Solicita al usuario el nombre del proyecto y su ubicación geográfica exacta.
2. Pide que el usuario proporcione (mediante texto o documentos) los detalles del proyecto.
3. Extrae y estructura obligatoriamente tres pilares: 
   A) Detalles Técnicos: Tipologías (m2, habitaciones, baños), amenidades y características de construcción. 
   B) Detalles Comerciales: Precios desde, formas de pago, bonos o descuentos aplicables y fechas de entrega. 
   C) Inventario: Unidades disponibles o fases de venta actuales.
4. Si falta información en alguno de los 3 pilares, pregúntale al usuario proactivamente para completarla.
5. Presenta la información extraída en formato JSON o Markdown estructurado para su validación final en el sistema.""",
            "guardrails_prompt": """NUNCA inventes precios, amenidades, fechas de entrega ni unidades en inventario. NO asumas datos que no estén explícitamente en el texto o documento proporcionado por el usuario. Si la información proporcionada es contradictoria, detente y pide una aclaración inmediata. Tu única función es estructurar datos, no vender el proyecto."""
        }

        # --- C. PROMPTS DE VENTAS ---
        ai_config.agent_ventas = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """Eres el Agente IA de Ventas Inmobiliarias de Black Penguin. Tu objetivo es calificar prospectos que llegan vía SMS y agendar reuniones con los brokers asignados al proyecto.""",
            "protocol_prompt": """1. Saluda cordialmente al prospecto y confirma su interés en el proyecto.
2. Califica el presupuesto, tiempo de compra y preferencia de tipología.
3. Consulta la disponibilidad del broker y propone fecha/hora para la cita.""",
            "guardrails_prompt": """No des información no confirmada sobre precios finales o descuentos sin validación."""
        }

        # --- D. PROMPTS DE REPORTERÍA ---
        ai_config.agent_reporteria = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """Eres el Analista de Datos de Ventas IA de Black Penguin.""",
            "protocol_prompt": """Genera resúmenes ejecutivos sobre el embudo de ventas, tasa de conversión y desempeño de inventario.""",
            "guardrails_prompt": """Basa tus análisis únicamente en las métricas reales del sistema."""
        }
        
        flag_modified(ai_config, "available_models")
        flag_modified(ai_config, "agent_onboarding_empresa")
        flag_modified(ai_config, "agent_onboarding_proyectos")
        flag_modified(ai_config, "agent_ventas")
        flag_modified(ai_config, "agent_reporteria")
        
        db.commit()
        print("✅ Configuración de IA y Prompts inyectados con éxito.")

        # =======================================================
        # ⚙️ 3. SEMBRAR CONFIGURACIÓN DE SERVICIOS EXTERNOS (Firebase / Twilio)
        # =======================================================
        firebase_config = db.query(FirebaseConfig).first()
        if not firebase_config:
            firebase_config = FirebaseConfig()
            db.add(firebase_config)
            print("⚙️ Configuración inicial de Firebase creada.")

        twilio_config = db.query(TwilioConfig).first()
        if not twilio_config:
            twilio_config = TwilioConfig()
            db.add(twilio_config)
            print("⚙️ Configuración inicial de Twilio creada.")

        db.commit()

        # =======================================================
        # 💼 4. SEMBRAR PLAN BÁSICO DE SUSCRIPCIÓN
        # =======================================================
        print("💼 Sembrando Plan de Suscripción Base...")
        existing_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == "Basic").first()
        
        if not existing_plan:
            basic_plan = SubscriptionPlan(
                name="Basic",
                description="Basic Plan",
                max_admins=1,
                max_mkt_users=5,
                max_sales_users=5,
                max_projects=5,
                max_properties_per_project=50,
                is_active=True
            )
            db.add(basic_plan)
            db.commit()
            print("✅ Plan 'Basic' creado con éxito.")
        else:
            print("✅ El plan 'Basic' ya existe en la base de datos.")

    except Exception as e:
        print(f"❌ Error crítico durante el Data Seeding: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db()