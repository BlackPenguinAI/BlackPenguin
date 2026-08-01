from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SqlaEnum
from sqlalchemy.orm import relationship
import enum
import uuid
from datetime import datetime
from app.db.postgres import Base

class SenderType(str, enum.Enum):
    USER = "user"
    AI = "ai"   

class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # 1. Identidad
    legal_name = Column(String(255), nullable=True)
    dba = Column(String(255), nullable=True)
    headquarters = Column(String(255), nullable=True)
    year_established = Column(String(4), nullable=True)
    
    # 2. Equipo y Contactos
    executive_team = Column(JSON, default=list) 
    
    # 3. Enfoque
    asset_classes = Column(JSON, default=list) 
    
    # 4. Mercado
    market_coverage = Column(String(255), nullable=True)
    target_demographics = Column(Text, nullable=True)
    
    # 5. Estrategia
    aum = Column(String(100), nullable=True)
    investment_strategy = Column(Text, nullable=True)
    
    # 6. Propuesta de Valor
    value_proposition = Column(Text, nullable=True)
    key_differentiators = Column(Text, nullable=True)
    
    # 7. Marca
    tone_of_voice = Column(String(100), nullable=True)
    key_messaging = Column(Text, nullable=True)
    
    # Flags de completitud
    is_identity_completed = Column(Boolean, default=False)
    is_team_completed = Column(Boolean, default=False)
    is_focus_completed = Column(Boolean, default=False)
    is_market_completed = Column(Boolean, default=False)
    is_strategy_completed = Column(Boolean, default=False)
    is_value_prop_completed = Column(Boolean, default=False)
    is_brand_completed = Column(Boolean, default=False)
    is_profile_fully_completed = Column(Boolean, default=False)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    messages = relationship("OnboardingMessage", back_populates="session", cascade="all, delete-orphan")

class OnboardingMessage(Base):
    __tablename__ = "onboarding_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False) 
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    session = relationship("OnboardingSession", back_populates="messages")