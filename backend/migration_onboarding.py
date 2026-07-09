from app.db.postgres import engine
from app.modules.tenants.models import OnboardingProtocol, OnboardingSession, OnboardingMessage
OnboardingProtocol.__table__.create(engine, checkfirst=True)
OnboardingSession.__table__.create(engine, checkfirst=True)
OnboardingMessage.__table__.create(engine, checkfirst=True)
print("✅ ¡Tablas de Inteligencia Artificial y Onboarding creadas con éxito!")