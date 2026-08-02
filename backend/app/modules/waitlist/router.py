from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from .models import WaitlistEntry
from .schemas import WaitlistCreate, WaitlistResponse

router = APIRouter()

# 🌐 PÚBLICO: Recibe el correo desde la Landing Page
@router.post("/", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(payload: WaitlistCreate, db: Session = Depends(get_db)):
    existing = db.query(WaitlistEntry).filter(WaitlistEntry.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already on the waitlist.")
    
    new_entry = WaitlistEntry(email=payload.email)
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry

# 🔒 PROTEGIDO: Lista los correos en el panel de Superadmin
@router.get("/", response_model=List[WaitlistResponse])
def get_waitlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return db.query(WaitlistEntry).order_by(WaitlistEntry.created_at.desc()).all()

# 🔒 PROTEGIDO: Eliminar un registro del waitlist
@router.delete("/{entry_id}", status_code=status.HTTP_200_OK)
def delete_waitlist_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    
    db.delete(entry)
    db.commit()
    return {"detail": "Entry deleted successfully."}