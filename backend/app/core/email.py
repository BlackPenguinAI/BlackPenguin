# backend/app/core/email.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

def send_email(to_email: str, subject: str, html_content: str):
    """Motor de envío de correos. Si no hay credenciales SMTP, imprime el correo en consola (Modo Dev)."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        print(f"\n--- 📧 SIMULACIÓN DE CORREO A: {to_email} ---")
        print(f"ASUNTO: {subject}")
        print(f"CONTENIDO:\n{html_content}")
        print("------------------------------------------\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT)
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAILS_FROM_EMAIL, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"❌ Error crítico enviando correo a {to_email}: {e}")