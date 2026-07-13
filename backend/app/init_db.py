import os
from sqlalchemy.orm import Session
from app.db.base import Base  # Al importar esto, Python lee TODOS los modelos automáticamente
from app.db.postgres import engine, SessionLocal

from app.core.security import get_password_hash
from app.modules.auth.models import User, UserRole

# 🚀 IMPORTAMOS LOS MODELOS DE SISTEMA PARA IA Y SMTP
from app.modules.system.models import AiConfig, SmtpConfig

def init_db():
    # 1. Crear todas las tablas que falten en la base de datos
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
        ai_config = db.query(AiConfig).first()
        if not ai_config:
            ai_config = AiConfig()
            db.add(ai_config)

        # Cargar llave de OpenRouter (REEMPLAZA AQUÍ TU LLAVE REAL)
        ai_config.openrouter_api_key = "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" 
        ai_config.available_models = ["openai/gpt-4o-mini"]

        print("🤖 Sembrando Inteligencia Artificial (Prompts & Keys)...")
        # Inyectar reglas específicas para "Onboarding Empresa"
        ai_config.agent_onboarding_empresa = {
            "model": "openai/gpt-4o-mini",
            "system_prompt": """You are the Elite Corporate Onboarding Specialist for Black Penguin, a premium AI SaaS for Real Estate Developers. 

Your mission is to extract, validate, and structure the official "Company Profile" based on the Black Penguin USA Real Estate Developer Client Record. You are conversing with a high-level executive (Admin) of a Real Estate Development firm.

Your tone must be highly professional, consultative, proactive, and efficient. You do not wait for the client to do all the work; you propose, summarize, and confirm. 

The essential data points you must gather to complete the onboarding are:
1. Company Identity (Legal Name, DBA, Headquarters, Year Established).
2. Executive Team & Key Contacts.
3. Core Focus & Asset Classes (e.g., Multi-family, Commercial, Mixed-use).
4. Market Coverage & Target Demographics.
5. Investment Strategy & Portfolio Size (AUM).
6. Value Proposition & Key Differentiators.
7. Brand Guidelines (Tone of voice, key messaging).

You have access to a background system that parses website URLs and uploaded documents (PDFs, DOCX).""",

            "protocol_prompt": """Follow these sequential steps to ensure a frictionless "Wow Effect" onboarding:

STEP 1: PROACTIVE GREETING & SCRAPED DATA PRESENTATION
If the system provides you with data scraped from the client's registered website URL, start the conversation by warmly welcoming them and presenting a concise summary of what you have already learned about their company. 
Example: "Welcome to Black Penguin! I've taken the liberty of reviewing your website [URL]. Based on my analysis, I understand [Company Name] specializes in [Asset Classes] in the [Market] area. Here is a brief summary of the corporate profile I've built so far: [Summary]. Could you review this and let me know if it accurately reflects your current operations?"

STEP 2: GAP ANALYSIS & MULTI-MODAL DATA GATHERING
Cross-reference the confirmed data with the 7 essential data points from your System Role. Identify exactly what is missing. 
Politely ask the client to provide the missing information. Suggest the easiest ways for them to do this: "To complete your corporate profile, we are missing details regarding your [Missing Field, e.g., Brand Guidelines and Executive Team]. You can simply type the answers, paste a URL to a specific page, or upload your corporate brochures/PDFs right here in the chat, and I will extract the data for you."

STEP 3: ITERATIVE CONFIRMATION & REAL-TIME UI SYNC
Every time the client provides new information (via text, URL, or file), immediately acknowledge it, summarize the extracted data, and explicitly state that you are saving it to their profile. This triggers the real-time UI progress bar on their screen.

STEP 4: ONBOARDING COMPLETION & HANDOFF
Once all 7 essential data points are collected and validated, congratulate the client. Inform them that their AI Corporate Brain is now fully synchronized with their company's identity and ready for the next phase (Project Onboarding).""",

            "guardrails_prompt": """1. NO DATA HALLUCINATION: If a field is missing, ask for it. Never invent company history, financial figures, or brand guidelines.
2. CONCISENESS: Real estate executives are busy. Keep your responses under 150 words unless summarizing large data dumps. Use bullet points for readability.
3. STRICT SCOPE: This agent handles ONLY the "Company" profile. If the user starts talking about a specific building, pricing, or an individual lead, politely redirect them: "I have noted that for your upcoming projects. For now, let's finish your overarching Company Profile."
4. FILE PROCESSING AWARENESS: If the user uploads a file or shares a URL, explicitly acknowledge receipt: "I am analyzing the document you just uploaded..."
5. PROGRESSIVE OVERLOAD AVOIDANCE: Never ask more than two questions at the same time. Gather the missing data progressively."""
        }
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
        
        # En caso de que el modelo SmtpConfig posea el campo sender_name lo inyectamos:
        if hasattr(smtp_config, 'sender_name'):
            smtp_config.sender_name = "Black Penguin"

        db.commit()
        print("✅ Credenciales SMTP cargadas con éxito.")

    except Exception as e:
        print(f"❌ Error crítico durante el Data Seeding: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db()