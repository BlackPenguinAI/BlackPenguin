from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.projects.completion import calculate_completion
from app.modules.projects.models import Project, ProjectCampaign, ProjectProfile, ProjectSession, ProjectUnit
from app.modules.brokers.models import Broker
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_crm.models import FunnelStage, Lead, Meeting, MeetingStatus

from .template import CAMPAIGNS, FIELD_STATES, LEADS, PROFILE_DATA, TEMPLATE_VERSION, UNITS


def provision_demo_project(
    db: Session,
    *,
    company_id: str,
    approved_by_user_id: str,
    template_version: str = TEMPLATE_VERSION,
) -> Project:
    """Create or reset the legacy synthetic Demo Project for tests and explicit tooling."""
    project = db.query(Project).filter(
        Project.company_id == company_id,
        Project.is_demo.is_(True),
        Project.demo_template_version == template_version,
    ).first()
    now = datetime.utcnow()
    if not project:
        project = Project(
            company_id=company_id,
            name="Demo",
            description=PROFILE_DATA["short_description"],
            address=PROFILE_DATA["exact_address"],
            city=PROFILE_DATA["city"],
            country=PROFILE_DATA["country"],
            is_active=True,
            is_demo=True,
        )
        db.add(project)
        db.flush()
        db.add(ProjectSession(project_id=project.id))
        profile = ProjectProfile(project_id=project.id)
        db.add(profile)
    else:
        profile = project.profile or ProjectProfile(project_id=project.id)
        if not project.profile:
            db.add(profile)
        db.query(SalesConversation).filter(SalesConversation.project_id == project.id).delete(synchronize_session=False)
        db.query(Meeting).filter(Meeting.project_id == project.id).delete(synchronize_session=False)
        db.query(Broker).filter(Broker.project_id == project.id).delete(synchronize_session=False)
        db.query(ProjectUnit).filter(ProjectUnit.project_id == project.id).delete(synchronize_session=False)
        db.query(ProjectCampaign).filter(ProjectCampaign.project_id == project.id).delete(synchronize_session=False)
        db.query(Lead).filter(Lead.project_id == project.id, Lead.is_demo.is_(True)).delete(synchronize_session=False)

    project.name = "Demo"
    project.is_active = True
    project.is_demo = True
    project.demo_template_version = template_version
    project.onboarding_status = "completed"
    project.onboarding_completed_at = now
    project.onboarding_approved_by_user_id = approved_by_user_id

    profile.profile_data = dict(PROFILE_DATA)
    profile.field_states = {key: dict(value) for key, value in FIELD_STATES.items()}
    profile.field_sources = {key: {"type": "demo_template", "reference": template_version} for key in FIELD_STATES}
    completion = calculate_completion(profile.field_states, final_approved=True)
    profile.completion_percentage = completion["percentage"]
    profile.final_approved = True
    profile.sales_activation_status = "demo_only"
    profile.inventory_last_updated_at = now
    profile.approved_for_sales_at = now

    for code, typology, area, bedrooms, bathrooms, price, unit_status in UNITS:
        db.add(ProjectUnit(
            project_id=project.id,
            unit_code=code,
            typology=typology,
            area=Decimal(area),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            list_price=Decimal(price),
            currency="USD",
            status=unit_status,
            inventory_updated_at=now,
        ))
    campaigns = []
    for name, objective, campaign_status in CAMPAIGNS:
        campaign = ProjectCampaign(
            project_id=project.id,
            name=name,
            platform="demo",
            objective=objective,
            status=campaign_status,
        )
        db.add(campaign)
        campaigns.append(campaign)
    db.flush()
    leads = []
    for index, (name, phone, email, stage, score) in enumerate(LEADS):
        lead = Lead(
            company_id=company_id,
            project_id=project.id,
            campaign_id=campaigns[index % len(campaigns)].id,
            full_name=name,
            phone=phone,
            email=email,
            source="Demo campaign",
            platform="demo",
            external_lead_id=f"demo:{company_id}:{index + 1}",
            preferred_channel="simulation",
            consent_status="demo",
            intent_score=score,
            funnel_stage=FunnelStage(stage),
            agent_status="simulation",
            is_demo=True,
            last_interaction_at=now - timedelta(minutes=(index + 1) * 17),
            next_action_at=now + timedelta(hours=index + 2),
        )
        db.add(lead)
        leads.append(lead)
    db.flush()

    broker = Broker(
        project_id=project.id, first_name="Alex", last_name="Morgan",
        email="demo-broker@example.invalid", google_calendar_id=None,
    )
    db.add(broker); db.flush()
    db.add(Meeting(
        project_id=project.id, lead_id=leads[3].id, broker_id=broker.id,
        meeting_time=now + timedelta(days=2, hours=3), duration_minutes=45,
        modality="virtual", confirmation_status="confirmed",
        calendar_sync_status="demo", status=MeetingStatus.CONFIRMED,
        notes="Synthetic appointment for the Agent and Sales demo.",
    ))

    demo_threads = (
        (("assistant", "Hi Sofia, this is the Demo Project assistant. What kind of home are you considering?"),),
        (("user", "I am comparing one and two bedroom homes."),
         ("assistant", "I can help with that. Is your priority a lower starting price or more space?")),
        (("user", "My budget is around $700,000 and I prefer two bedrooms."),
         ("assistant", "The confirmed demo inventory includes two-bedroom options. When are you hoping to buy?")),
        (("user", "I would like a virtual appointment this week."),
         ("assistant", "Your demo appointment request is ready for the Sales team to review.")),
    )
    for index, lead in enumerate(leads):
        conversation = SalesConversation(
            company_id=company_id, project_id=project.id, campaign_id=lead.campaign_id,
            lead_id=lead.id, channel="simulation", stage=lead.funnel_stage.value,
            automation_level=1, is_paused=False, pause_reason=None,
            created_at=now - timedelta(days=2), updated_at=lead.last_interaction_at or now,
        )
        db.add(conversation); db.flush()
        for message_index, (role, content) in enumerate(demo_threads[index]):
            db.add(SalesMessage(
                conversation_id=conversation.id, channel="simulation",
                direction="inbound" if role == "user" else "outbound",
                role=role, content=content,
                status="received" if role == "user" else "simulated",
                created_at=(lead.last_interaction_at or now) + timedelta(minutes=message_index),
            ))
    return project
