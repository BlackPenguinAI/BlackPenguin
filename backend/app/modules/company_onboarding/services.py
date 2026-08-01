from sqlalchemy.orm import Session
from .models import CompanyProfile, OnboardingSession, OnboardingMessage, SenderType

def get_or_create_profile(db: Session, company_id: str) -> CompanyProfile:
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).first()
    if not profile:
        profile = CompanyProfile(company_id=company_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile

def get_or_create_session(db: Session, company_id: str) -> OnboardingSession:
    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == company_id).first()
    if not session:
        session = OnboardingSession(company_id=company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session

def save_message(db: Session, session_id: str, sender: SenderType, content: str):
    msg = OnboardingMessage(session_id=session_id, sender=sender, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg