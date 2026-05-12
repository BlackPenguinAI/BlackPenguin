from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Black Penguin API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Seguridad
    SECRET_KEY: str = "CAMBIAR_POR_UNA_LLAVE_MUY_SEGURA_2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 1 semana

    # Bases de Datos (Docker/K3s local en DigitalOcean)
    POSTGRES_SERVER: str = "127.0.0.1"
    POSTGRES_USER: str = "superadmin_bp"
    POSTGRES_PASSWORD: str = "bp_secure_password_2026!"
    POSTGRES_DB: str = "blackpenguin_core"

    # DigitalOcean Spaces
    DO_SPACES_KEY: Optional[str] = None
    DO_SPACES_SECRET: Optional[str] = None
    DO_SPACES_REGION: str = "nyc3"
    DO_SPACES_BUCKET: str = "blackpenguin-assets"

    class Config:
        env_file = ".env"

settings = Settings()