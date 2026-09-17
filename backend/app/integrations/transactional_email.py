"""Minimal SMTP transport for appointment confirmations.

Authentication/invitation mail remains in Firebase. This transport is only for
operational messages generated after a verified appointment transaction.
"""

from email.message import EmailMessage
import smtplib

from app.core.config import settings


def send_appointment_email(*, recipient: str, subject: str, body: str, ics_content: str) -> None:
    if not settings.SMTP_SERVER or not settings.EMAILS_FROM_EMAIL:
        raise RuntimeError("Transactional email transport is not configured.")
    message = EmailMessage()
    message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        ics_content.encode("utf-8"),
        maintype="text", subtype="calendar", filename="black-penguin-appointment.ics",
        params={"method": "PUBLISH"},
    )
    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=20) as client:
        client.starttls()
        if settings.SMTP_USER:
            client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        client.send_message(message)
