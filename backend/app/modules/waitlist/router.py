from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.postgres import get_db
# Nota temporal: Mantenemos el import de auth antiguo hasta la Fase 2
from app.modules.auth.deps import RoleChecker 
from app.modules.users.models import User, UserRole

from .schemas import WaitlistRequest, WaitlistResponse
from . import services

router = APIRouter()

@router.post("/", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(payload: WaitlistRequest, db: Session = Depends(get_db)):
    """Añade un correo a la lista de espera (Endpoint Público)."""
    return services.add_email_to_waitlist(db, payload)

@router.delete("/{email_id}", status_code=status.HTTP_200_OK)
def delete_waitlist_email(
    email_id: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    """Elimina un correo de la lista de espera (Solo Staff)."""
    services.remove_email_from_waitlist(db, email_id)
    return {"message": "Registro eliminado exitosamente."}