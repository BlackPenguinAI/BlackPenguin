from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Black Penguin Core API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Seguridad JWT
    SECRET_KEY: str = "BLACK_PENGUIN_SUPER_SECRET_KEY_FOR_LOCAL_SIGNING_2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 Semana

    # Conexión Base de Datos Relacional (PostgreSQL)
    # Por defecto apunta al localhost de Docker Compose
    DATABASE_URL: str = "postgresql://superadmin_bp:bp_secure_password_2026!@localhost:5433/blackpenguin_core"

    class Config:
        env_file = ".env"

settings = Settings()