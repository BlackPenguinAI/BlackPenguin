from sqlalchemy import Boolean, Column, String, DateTime, ForeignKey, JSON, Text
import uuid
from datetime import datetime
from app.db.postgres import Base

# =========================================================
# ⚙️ CONFIGURACIÓN DE SERVICIOS EXTERNOS Y LEGALES
# =========================================================

class FirebaseConfig(Base):
    __tablename__ = "firebase_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key = Column(String(255), nullable=True)
    auth_domain = Column(String(255), nullable=True)
    project_id = Column(String(255), nullable=True)
    service_account_ciphertext = Column(Text, nullable=True)
    service_account_hint = Column(String(255), nullable=True)
    is_enabled = Column(Boolean, default=False, nullable=False)
    verification_status = Column(String(30), default="not_configured", nullable=False)
    verified_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    auth_mode = Column(String(20), default="rest", nullable=False)
    action_handler_url = Column(String(500), default="https://blackpenguin.ai/activate-account", nullable=False)
    # Legacy plaintext column retained only so the migration can encrypt it.
    credentials_json = Column(Text, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TwilioConfig(Base):
    __tablename__ = "twilio_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_sid = Column(String(255), nullable=True)
    # Kept temporarily for a non-destructive migration from the legacy schema.
    auth_token = Column(String(255), nullable=True)
    auth_token_ciphertext = Column(Text, nullable=True)
    auth_token_hint = Column(String(12), nullable=True)
    from_phone_number = Column(String(50), nullable=True)
    live_sms_enabled = Column(Boolean, default=False, nullable=False)
    verification_status = Column(String(30), default="not_configured", nullable=False)
    verified_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GoogleCalendarConfig(Base):
    __tablename__ = "google_calendar_configurations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(255), nullable=True)
    client_secret_ciphertext = Column(Text, nullable=True)
    client_secret_hint = Column(String(12), nullable=True)
    redirect_uri = Column(String(500), nullable=False)
    is_enabled = Column(Boolean, default=False, nullable=False)
    verification_status = Column(String(30), default="not_configured", nullable=False)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CalendarOAuthAttempt(Base):
    __tablename__ = "calendar_oauth_attempts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    nonce_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MetaPlatformConfig(Base):
    __tablename__ = "meta_platform_configurations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    app_id = Column(String(100), nullable=True)
    app_secret_ciphertext = Column(Text, nullable=True)
    app_secret_hint = Column(String(12), nullable=True)
    login_config_id = Column(String(150), nullable=True)
    graph_api_version = Column(String(20), default="v20.0", nullable=False)
    redirect_uri = Column(String(500), nullable=False)
    webhook_callback_url = Column(String(500), nullable=False)
    webhook_verify_token_ciphertext = Column(Text, nullable=True)
    webhook_verify_token_hint = Column(String(12), nullable=True)
    requested_scopes = Column(JSON, default=list, nullable=False)
    is_enabled = Column(Boolean, default=False, nullable=False)
    verification_status = Column(String(30), default="not_configured", nullable=False)
    app_review_status = Column(String(30), default="pending", nullable=False)
    business_verification_status = Column(String(30), default="pending", nullable=False)
    verified_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MetaOAuthAttempt(Base):
    __tablename__ = "meta_oauth_attempts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    nonce_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class LegalDocument(Base):
    __tablename__ = "legal_documents"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_type = Column(String(50), nullable=False)  # 'privacy' o 'terms'
    language = Column(String(10), nullable=False, default="en")  # 'en' o 'es'
    last_updated_label = Column(String(100), nullable=True, default="July 2026")
    content_markdown = Column(Text, nullable=False)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
