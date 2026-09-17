"""Trigger Email from Firestore transport for appointment confirmations."""

import base64

from app.core.config import settings
from app.integrations.firebase_admin_client import enqueue_email


def send_appointment_email(*, document_id: str, recipient: str, subject: str, body: str,
                           html: str, ics_content: str, from_email: str | None = None,
                           reply_to: str | None = None, mail_collection: str = "mail",
                           project_id: str | None = None) -> dict:
    firebase_project_id = project_id or settings.FIREBASE_PROJECT_ID
    if not firebase_project_id:
        raise RuntimeError("Firebase Project ID is not configured.")
    return enqueue_email(
        project_id=firebase_project_id,
        document_id=document_id,
        recipient=recipient,
        subject=subject,
        text=body,
        html=html,
        from_email=from_email or (f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>" if settings.EMAILS_FROM_EMAIL else None),
        reply_to=reply_to or settings.EMAILS_FROM_EMAIL or None,
        mail_collection=mail_collection,
        attachments=[{
            "filename": "black-penguin-appointment.ics",
            "content": base64.b64encode(ics_content.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "contentType": "text/calendar; method=PUBLISH",
        }],
    )
