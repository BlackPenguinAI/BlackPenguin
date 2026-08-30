from datetime import datetime, timedelta
from urllib.parse import urlencode

from jose import jwt

from app.core.config import settings


def calendar_invite_url(meeting_id: str) -> str:
    token = jwt.encode({"meeting_id": meeting_id, "purpose": "calendar_invite", "exp": datetime.utcnow() + timedelta(days=90)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/sales/public/meetings/{meeting_id}.ics?token={token}"


def google_calendar_add_url(*, project, lead, starts_at: datetime, duration_minutes: int = 45) -> str:
    end = starts_at + timedelta(minutes=duration_minutes)
    compact = lambda value: value.strftime("%Y%m%dT%H%M%SZ")
    location = ", ".join(
        value for value in (project.name, project.address, project.city, project.country) if value
    )
    params = {
        "action": "TEMPLATE",
        "text": f"{project.name} property visit",
        "dates": f"{compact(starts_at)}/{compact(end)}",
        "details": f"Appointment for {lead.full_name}, coordinated by Black Penguin AI Sales Agent.",
        "location": location,
    }
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"
