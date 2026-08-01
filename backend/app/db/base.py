# backend/app/db/base.py
from app.db.postgres import Base

# 🚀 IMPORTAMOS TODOS LOS MODELOS DE LOS MICRO-MÓDULOS DDD
# Esto es vital para que SQLAlchemy cree todas las tablas con Base.metadata.create_all()

from app.modules.waitlist.models import WaitlistEmail
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.companies.models import Company
from app.modules.users.models import User
from app.modules.system_settings.models import FirebaseConfig, TwilioConfig, LegalDocument
from app.modules.ai_core.models import AIConfiguration
from app.modules.company_onboarding.models import CompanyProfile, OnboardingSession, OnboardingMessage
from app.modules.projects.models import Project, ProjectProfile, ProjectSession, ProjectMessage
from app.modules.brokers.models import Broker
from app.modules.sales_crm.models import Lead, SmsChatMessage, Meeting