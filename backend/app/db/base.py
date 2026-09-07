# backend/app/db/base.py
from app.db.postgres import Base

# 🚀 IMPORTAMOS TODOS LOS MODELOS DE LOS MICRO-MÓDULOS DDD
# Esto es vital para que SQLAlchemy cree todas las tablas con Base.metadata.create_all()

from app.modules.waitlist.models import WaitlistEntry
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.companies.models import Company
from app.modules.users.models import User
from app.modules.system_settings.models import (
    CalendarOAuthAttempt, FirebaseConfig, GoogleCalendarConfig, LegalDocument,
    MetaOAuthAttempt, MetaPlatformConfig, TwilioConfig,
)
from app.modules.ai_core.models import AIConfiguration, PromptVersion
from app.modules.company_onboarding.models import (
    CompanyOnboardingProposal,
    CompanyOnboardingSource,
    CompanyProfile,
    CompanyMediaAsset,
    OnboardingMessage,
    OnboardingSession,
)
from app.modules.projects.models import (
    MetaConnection,
    MetaAuthorization,
    Project,
    ProjectCampaign,
    ProjectMessage,
    ProjectOnboardingProposal,
    ProjectOnboardingSource,
    ProjectProfile,
    ProjectSession,
    ProjectUnit,
    ProjectPropertyType,
    ProjectPropertyTypeMedia,
    SalesAssetShare,
)
from app.modules.brokers.models import Broker
from app.modules.sales_crm.models import (
    CalendarConnection, Lead, LeadConsentEvent, LeadContact, LeadObjection,
    LeadScoreSnapshot, LeadSegmentAssignment, LeadStageHistory, Meeting,
    MeetingAttachment, SalesAvailabilityBlock, SalesAvailabilityWindow,
    SmsChatMessage,
)
from app.modules.project_team.models import ProjectRoutingState, ProjectUserAssignment
from app.modules.sales_agent.models import AgentRun, ExternalWebhookEvent, OutboundMessage, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.seo.models import SeoAuditRun
from app.db.schema import SchemaVersion
