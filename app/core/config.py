from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # =================================================================
    # Configuración General
    # =================================================================
    PROJECT_NAME: str = "Black Penguin Core API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"
    
    # =================================================================
    # Variables Sensibles e Infraestructura (Desde el .env)
    # =================================================================
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DATABASE_URL: str
    MONGO_URL: str = "mongodb://localhost:27017/blackpenguin_db"
    ENVIRONMENT: str

    # Credenciales iniciales
    FIRST_SUPERADMIN_EMAIL: str
    FIRST_SUPERADMIN_PASSWORD: str

    # Credenciales de Meta
    META_ACCESS_TOKEN: str
    META_VERIFY_TOKEN: str = "blackpenguin_meta_token_2026"
    META_APP_SECRET: str = "app_secret_de_meta_pendiente"
    META_API_VERSION: str = "v20.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()