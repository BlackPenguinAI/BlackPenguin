from sqlalchemy.orm import Session
from app.modules.users.models import User
from app.core.security import create_email_token
from app.integrations.firebase_client import send_activation_email

def send_user_activation(user: User):
    """Genera token de 1 uso y dispara Firebase."""
    token = create_email_token(email=user.email, user_hash=user.hashed_password)
    # Aquí irá la URL de tu frontend
    activation_link = f"https://blackpenguin.ai/set-password?token={token}"
    send_activation_email(user.email, activation_link)