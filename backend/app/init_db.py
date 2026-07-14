import os
from sqlalchemy.orm import Session
from app.db.base import Base  
from app.db.postgres import engine, SessionLocal
from sqlalchemy.orm.attributes import flag_modified # 🚀 TRUCO PARA GUARDAR JSON

from app.core.security import get_password_hash
from app.modules.auth.models import User, UserRole

# 🚀 IMPORTAMOS DESDE TUS MÓDULOS CORRECTOS
from app.modules.ai.models import AIConfiguration 
from app.modules.system.models import SmtpConfig
from app.modules.tenants.models import SubscriptionPlan # 🚀 NUEVO: Modelo de Planes

def init_db():
    print("🔄 Verificando tablas en la base de datos...")
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
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
        # 🧠 2. SEMBRAR AI KEYS & AI CONFIG (Agent Onboarding)
        # =======================================================
        print("🤖 Sembrando Inteligencia Artificial (Prompts & Keys)...")
        ai_config = db.query(AIConfiguration).first()
        if not ai_config:
            ai_config = AIConfiguration()
            db.add(ai_config)

        ai_config.openrouter_api_key = "sk-or-v1-PON_TU_LLAVE_REAL_AQUI" 
        ai_config.available_models = ["openai/gpt-4o-mini"]

        ai_config.agent_onboarding_empresa = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """You are the Elite Corporate Onboarding Specialist for Black Penguin, a premium AI SaaS for Real Estate Developers. \n\nYour mission is to extract, validate, and structure the official "Company Profile" based on the Black Penguin USA Real Estate Developer Client Record. You are conversing with a high-level executive (Admin) of a Real Estate Development firm.\n\nYour tone must be highly professional, consultative, proactive, and efficient. You do not wait for the client to do all the work; you propose, summarize, and confirm. \n\nThe essential data points you must gather to complete the onboarding are:\n1. Company Identity (Legal Name, DBA, Headquarters, Year Established).\n2. Executive Team & Key Contacts.\n3. Core Focus & Asset Classes (e.g., Multi-family, Commercial, Mixed-use).\n4. Market Coverage & Target Demographics.\n5. Investment Strategy & Portfolio Size (AUM).\n6. Value Proposition & Key Differentiators.\n7. Brand Guidelines (Tone of voice, key messaging).\n\nYou have access to a background system that parses website URLs and uploaded documents (PDFs, DOCX).""",
            
            "protocol_prompt": """Follow these sequential steps to ensure a frictionless "Wow Effect" onboarding:\n\nSTEP 1: PROACTIVE GREETING & SCRAPED DATA PRESENTATION\nIf the system provides you with data scraped from the client's registered website URL, start the conversation by warmly welcoming them and presenting a concise summary of what you have already learned about their company. \nExample: "Welcome to Black Penguin! I've taken the liberty of reviewing your website [URL]. Based on my analysis, I understand [Company Name] specializes in [Asset Classes] in the [Market] area. Here is a brief summary of the corporate profile I've built so far: [Summary]. Could you review this and let me know if it accurately reflects your current operations?"\n\nSTEP 2: GAP ANALYSIS & MULTI-MODAL DATA GATHERING\nCross-reference the confirmed data with the 7 essential data points from your System Role. Identify exactly what is missing. \nPolitely ask the client to provide the missing information. Suggest the easiest ways for them to do this: "To complete your corporate profile, we are missing details regarding your [Missing Field, e.g., Brand Guidelines and Executive Team]. You can simply type the answers, paste a URL to a specific page, or upload your corporate brochures/PDFs right here in the chat, and I will extract the data for you."\n\nSTEP 3: ITERATIVE CONFIRMATION & REAL-TIME UI SYNC\nEvery time the client provides new information (via text, URL, or file), immediately acknowledge it, summarize the extracted data, and explicitly state that you are saving it to their profile. This triggers the real-time UI progress bar on their screen.\n\nSTEP 4: ONBOARDING COMPLETION & HANDOFF\nOnce all 7 essential data points are collected and validated, congratulate the client. Inform them that their AI Corporate Brain is now fully synchronized with their company's identity and ready for the next phase (Project Onboarding).""",
            
            "guardrails_prompt": """1. NO DATA HALLUCINATION: If a field is missing, ask for it. Never invent company history, financial figures, or brand guidelines.\n2. CONCISENESS: Real estate executives are busy. Keep your responses under 150 words unless summarizing large data dumps. Use bullet points for readability.\n3. STRICT SCOPE: This agent handles ONLY the "Company" profile. If the user starts talking about a specific building, pricing, or an individual lead, politely redirect them: "I have noted that for your upcoming projects. For now, let's finish your overarching Company Profile."\n4. FILE PROCESSING AWARENESS: If the user uploads a file or shares a URL, explicitly acknowledge receipt: "I am analyzing the document you just uploaded..."\n5. PROGRESSIVE OVERLOAD AVOIDANCE: Never ask more than two questions at the same time. Gather the missing data progressively."""
        }
        
        flag_modified(ai_config, "available_models")
        flag_modified(ai_config, "agent_onboarding_empresa")
        
        db.commit()
        print("✅ Configuración de IA y Prompts inyectados con éxito.")

        # =======================================================
        # 📧 3. SEMBRAR CONFIGURACIÓN SMTP (Notificaciones)
        # =======================================================
        smtp_config = db.query(SmtpConfig).first()
        if not smtp_config:
            smtp_config = SmtpConfig()
            db.add(smtp_config)

        print("📧 Sembrando credenciales SMTP...")
        smtp_config.smtp_host = "smtp.gmail.com"
        smtp_config.smtp_port = 587
        smtp_config.smtp_user = "info@blackpenguin.ai"
        smtp_config.smtp_password = "mimbak-venwat-9hobpY"
        smtp_config.smtp_security = "TLS"
        smtp_config.sender_email = "info@blackpenguin.ai"
        
        if hasattr(smtp_config, 'sender_name'):
            smtp_config.sender_name = "Black Penguin"

        db.commit()
        print("✅ Credenciales SMTP cargadas con éxito.")

        # =======================================================
        # 💼 4. SEMBRAR PLAN BÁSICO DE SUSCRIPCIÓN
        # =======================================================
        print("💼 Sembrando Plan de Suscripción Base...")
        existing_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == "Basic").first()
        
        if not existing_plan:
            basic_plan = SubscriptionPlan(
                name="Basic",
                description="Basic Plan",
                max_admins=5,
                max_mkt_users=5,
                max_sales_users=5,
                max_projects=5,
                max_properties_per_project=5,
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