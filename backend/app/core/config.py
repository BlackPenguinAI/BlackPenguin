from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Black Penguin Core API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"
    APP_COMMIT_SHA: str = "unknown"

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DATABASE_URL: str
    MONGO_URL: str = "mongodb://localhost:27017/blackpenguin_db"
    ENVIRONMENT: str

    FIRST_SUPERADMIN_EMAIL: str
    FIRST_SUPERADMIN_PASSWORD: str

    META_ACCESS_TOKEN: str
    META_VERIFY_TOKEN: str = "blackpenguin_meta_token_2026"
    META_APP_SECRET: str = "app_secret_de_meta_pendiente"
    META_API_VERSION: str = "v20.0"
    META_BUSINESS_MANAGER_ID: str = ""

    OPENROUTER_API_KEY: str
    DEFAULT_AI_MODEL: str = "deepseek/deepseek-chat"

    PROJECT_UPLOAD_ROOT: str = "./var/uploads"
    PUBLIC_APP_URL: str = "https://blackpenguin.ai"

    # Provider credentials are bootstrapped only when the database record is
    # empty. The Twilio Auth Token must be supplied through the environment and
    # is never returned by an API response.
    SETTINGS_ENCRYPTION_KEY: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_PHONE_NUMBER: str = "+18573824206"
    TWILIO_LIVE_SMS_ENABLED: bool = False

    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_REDIRECT_URI: str = "https://blackpenguin.ai/api/v1/sales/calendar/google/callback"

    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_API_KEY: str = ""
    FIREBASE_AUTH_DOMAIN: str = ""

    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "info@blackpenguin.ai"
    EMAILS_FROM_NAME: str = "Black Penguin"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
