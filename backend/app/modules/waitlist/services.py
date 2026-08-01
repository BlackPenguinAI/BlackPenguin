from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import WaitlistEmail
from .schemas import WaitlistRequest

def add_email_to_waitlist(db: Session, payload: WaitlistRequest) -> WaitlistEmail:
    existing_email = db.query(WaitlistEmail).filter(WaitlistEmail.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Este correo ya se encuentra en la lista de espera.")
    
    new_entry = WaitlistEmail(email=payload.email, language=payload.language)
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry

def remove_email_from_waitlist(db: Session, email_id: str):
    email_record = db.query(WaitlistEmail).filter(WaitlistEmail.id == email_id).first()
    if not email_record:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    
    db.delete(email_record)
    db.commit()