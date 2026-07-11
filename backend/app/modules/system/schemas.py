from pydantic import BaseModel, EmailStr

class SmtpConfigSchema(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_security: str
    sender_email: EmailStr