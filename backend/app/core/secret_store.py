"""Small encryption boundary for provider credentials stored in PostgreSQL."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet(seed: str | None = None) -> Fernet:
    seed = seed or settings.SETTINGS_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    seeds = [settings.SETTINGS_ENCRYPTION_KEY, settings.SECRET_KEY]
    for seed in dict.fromkeys(item for item in seeds if item):
        try:
            return _fernet(seed).decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            continue
    raise ValueError("Stored provider credential cannot be decrypted.")
