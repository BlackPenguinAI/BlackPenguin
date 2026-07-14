# backend/app/core/email.py
import smtplib
import socket # 🚀 IMPORTANTE: Librería nativa de red
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.db.postgres import SessionLocal
from app.modules.system.models import SmtpConfig

# ==============================================================================
# 🚀 HACK PARA DOCKER: Forzar IPv4
# Evita el error "[Errno 101] Network is unreachable" cuando Gmail devuelve IPv6
# ==============================================================================
old_getaddrinfo = socket.getaddrinfo
def ipv4_getaddrinfo(*args, **kwargs):
    responses = old_getaddrinfo(*args, **kwargs)
    # Filtramos para que solo devuelva rutas de la familia IPv4 (AF_INET)
    return [r for r in responses if r[0] == socket.AF_INET]
socket.getaddrinfo = ipv4_getaddrinfo
# ==============================================================================

def send_email(to_email: str, subject: str, html_content: str):
    """
    Motor de envío de correos. 
    Lee la configuración dinámica desde PostgreSQL (Angular Panel).
    """
    db = SessionLocal()
    try:
        smtp_config = db.query(SmtpConfig).first()

        if not smtp_config or not smtp_config.smtp_user or not smtp_config.smtp_password:
            print(f"\n--- 📧 SIMULACIÓN DE CORREO A: {to_email} ---")
            print(f"ASUNTO: {subject}")
            return

        smtp_host = smtp_config.smtp_host
        smtp_port = smtp_config.smtp_port
        smtp_user = smtp_config.smtp_user
        smtp_password = smtp_config.smtp_password
        sender_email = smtp_config.sender_email or smtp_user
        sender_name = getattr(smtp_config, 'sender_name', 'Black Penguin')

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        # Conexión forzada a IPv4 (gracias al parche de arriba)
        if smtp_config.smtp_security == "SSL":
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            if smtp_config.smtp_security == "TLS":
                server.starttls()
                
        server.login(smtp_user, smtp_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        
        print(f"✅ Correo enviado exitosamente a {to_email}")

    except Exception as e:
        print(f"❌ Error crítico enviando correo a {to_email}: {e}")
    finally:
        db.close()