from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

# 🚀 NUEVO: Tokens para Correos (Activación y Recuperación)
def create_email_token(email: str, user_hash: str = "", expires_delta: timedelta = timedelta(hours=24)) -> str:
    """Crea un token que expira en 24h y se amarra al hash actual de la contraseña (Un solo uso)."""
    expire = datetime.now(timezone.utc) + expires_delta
    # Guardamos los últimos 10 caracteres del hash. Si la contraseña cambia, el hash cambia.
    to_encode = {"exp": expire, "sub": email, "type": "email_action", "sec": user_hash[-10:] if user_hash else ""}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verify_email_token(token: str) -> dict | None:
    """Verifica el token y devuelve el diccionario completo si es válido."""
    try:
        decoded_token = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if decoded_token.get("type") != "email_action":
            return None
        return decoded_token
    except jwt.JWTError:
        return None


def create_invitation_state(
    invitation_id: str,
    user_id: str,
    expires_delta: timedelta = timedelta(days=7),
) -> str:
    """Create opaque, signed state for a Firebase email-link invitation."""
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "exp": expire,
        "sub": user_id,
        "invitation_id": invitation_id,
        "type": "firebase_invitation",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_invitation_state(token: str) -> dict | None:
    """Validate invitation state without exposing the invitee email in the URL."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "firebase_invitation":
            return None
        if not payload.get("sub") or not payload.get("invitation_id"):
            return None
        return payload
    except jwt.JWTError:
        return None
