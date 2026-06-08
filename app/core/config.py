from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # =================================================================
    # Configuración General (No sensible, puede tener valores por defecto)
    # =================================================================
    PROJECT_NAME: str = "Black Penguin Core API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"
    
    # =================================================================
    # Variables Sensibles e Infraestructura (Se cargan estrictamente desde el .env)
    # =================================================================
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DATABASE_URL: str
    ENVIRONMENT: str

    # =================================================================
    # Configuración de Carga del Entorno
    # =================================================================
    # SettingsConfigDict es el estándar moderno en Pydantic v2 para gestionar el .env
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignora variables adicionales que estén en el .env pero no use la app
    )

    # Credenciales iniciales
    FIRST_SUPERADMIN_EMAIL: str
    FIRST_SUPERADMIN_PASSWORD: str

    # Credenciales de Meta
    META_ACCESS_TOKEN: str = "token_de_prueba_pendiente"
    META_VERIFY_TOKEN: str = "blackpenguin_meta_token_2026"
    META_APP_SECRET: str = "app_secret_de_meta_pendiente"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instancia global inyectable en toda la aplicación
settings = Settings()