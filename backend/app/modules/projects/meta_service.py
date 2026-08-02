import base64
from datetime import datetime
import hashlib

from cryptography.fernet import Fernet
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings

from .models import MetaConnection


def _fernet() -> Fernet:
    # Derive a stable encryption key from the platform secret. Rotate with a dedicated key in a future vault migration.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def create_connection(db: Session, *, company_id: str, payload: dict) -> MetaConnection:
    token = payload.pop("access_token")
    connection = MetaConnection(
        company_id=company_id,
        token_ciphertext=_fernet().encrypt(token.encode("utf-8")).decode("ascii"),
        token_hint=f"••••{token[-4:]}",
        **payload,
    )
    db.add(connection); db.commit(); db.refresh(connection)
    return connection


async def verify_connection(db: Session, connection: MetaConnection) -> MetaConnection:
    token = _fernet().decrypt(connection.token_ciphertext.encode("ascii")).decode("utf-8")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://graph.facebook.com/{settings.META_API_VERSION}/me",
            params={"access_token": token, "fields": "id,name"}, timeout=20.0,
        )
        response.raise_for_status()
    connection.verified_at = datetime.utcnow()
    db.add(connection); db.commit(); db.refresh(connection)
    return connection
