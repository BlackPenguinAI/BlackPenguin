from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

# =========================================================================
# SCHEMAS DE EMAIL SETTINGS (FIREBASE)
# =========================================================================
class FirebaseConfigBase(BaseModel):
    api_key: Optional[str] = None
    auth_domain: Optional[str] = None
    project_id: Optional[str] = None
    credentials_json: Optional[str] = None

class FirebaseConfigUpdate(FirebaseConfigBase):
    pass

class FirebaseConfigSchema(FirebaseConfigBase):
    id: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# =========================================================================
# SCHEMAS DE MESSAGING SETTINGS (TWILIO)
# =========================================================================
class TwilioConfigUpdate(BaseModel):
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    from_phone_number: Optional[str] = None
    live_sms_enabled: Optional[bool] = None

class TwilioConfigSchema(BaseModel):
    id: Optional[str] = None
    account_sid: Optional[str] = None
    auth_token_configured: bool = False
    auth_token_hint: Optional[str] = None
    from_phone_number: Optional[str] = None
    live_sms_enabled: bool = False
    verification_status: str = "not_configured"
    verified_at: Optional[datetime] = None
    last_error: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# =========================================================================
# SCHEMAS DE DOCUMENTOS LEGALES
# =========================================================================
class LegalDocumentPayload(BaseModel):
    content_markdown: str
    last_updated_label: str

class LegalDocumentResponse(BaseModel):
    doc_type: str
    language: str
    last_updated_label: Optional[str] = "July 2026"
    content_markdown: str
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
