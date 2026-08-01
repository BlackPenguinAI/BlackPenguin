from datetime import datetime
import uuid

def create_calendar_event(calendar_id: str, title: str, start_time: datetime, attendee_email: str) -> str:
    """
    Simula la creación de un evento en Google Calendar.
    En producción, aquí se integrará la SDK oficial de Google (google-api-python-client).
    """
    print(f"\n--- 📅 GOOGLE CALENDAR SIMULATION ---")
    print(f"Calendar ID: {calendar_id}")
    print(f"Event: {title}")
    print(f"Time: {start_time}")
    print(f"Attendee: {attendee_email}")
    print("--------------------------------------\n")
    
    # Retornamos un ID de evento falso para simular la respuesta de Google
    return f"gcal_evt_{uuid.uuid4().hex[:12]}"