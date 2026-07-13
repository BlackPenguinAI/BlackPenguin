from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# =========================================================================
# SCHEMAS DE CONFIGURACIÓN SMTP
# =========================================================================
class SmtpConfigBase(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_security: str
    sender_email: str

class SmtpConfigUpdate(SmtpConfigBase):
    pass

class SmtpConfigSchema(SmtpConfigBase):
    id: Optional[str] = None
    
    class Config:
        from_attributes = True

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
    
    class Config:
        from_attributes = True