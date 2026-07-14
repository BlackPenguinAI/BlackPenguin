# backend/app/core/email.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 🚀 NUEVAS IMPORTACIONES PARA LEER LA BASE DE DATOS
from app.db.postgres import SessionLocal
from app.modules.system.models import SmtpConfig

def send_email(to_email: str, subject: str, html_content: str):
    """
    Motor de envío de correos. 
    Lee la configuración dinámica desde PostgreSQL (Angular Panel).
    Si no hay credenciales SMTP, imprime el correo en consola (Modo Dev).
    """
    # 1. Abrimos una sesión a la base de datos
    db = SessionLocal()
    try:
        # 2. Consultamos la configuración guardada por el Superadmin
        smtp_config = db.query(SmtpConfig).first()

        # 3. Si no hay configuración o faltan credenciales, simulamos en consola
        if not smtp_config or not smtp_config.smtp_user or not smtp_config.smtp_password:
            print(f"\n--- 📧 SIMULACIÓN DE CORREO A: {to_email} ---")
            print(f"ASUNTO: {subject}")
            print(f"CONTENIDO:\n{html_content}")
            print("------------------------------------------\n")
            return

        # 4. Extraemos las variables vivas
        smtp_host = smtp_config.smtp_host
        smtp_port = smtp_config.smtp_port
        smtp_user = smtp_config.smtp_user
        smtp_password = smtp_config.smtp_password
        sender_email = smtp_config.sender_email or smtp_user
        
        # Si el modelo tiene la columna sender_name, la usamos, si no "Black Penguin"
        sender_name = getattr(smtp_config, 'sender_name', 'Black Penguin')

        # 5. Preparamos el Mensaje
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        # 6. Conectamos al Servidor y Enviamos
        # Verificamos si usa SSL explícito (Puerto 465) o TLS (Puerto 587)
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
        # 7. Siempre cerramos la conexión a la BD
        db.close()