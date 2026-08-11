from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.projects.completion import calculate_completion
from app.modules.projects.models import Project, ProjectCampaign, ProjectProfile, ProjectSession, ProjectUnit

from app.modules.sales_crm.models import FunnelStage, Lead

from .template import CAMPAIGNS, FIELD_STATES, LEADS, PROFILE_DATA, TEMPLATE_VERSION, UNITS


def provision_demo_project(
    db: Session,
    *,
    company_id: str,
    approved_by_user_id: str,
    template_version: str = TEMPLATE_VERSION,
) -> Project:
    """Create or reset the single Demo Project without committing the caller's transaction."""
    project = db.query(Project).filter(
        Project.company_id == company_id,
        Project.is_demo.is_(True),
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
    for index, (name, phone, email, stage, score) in enumerate(LEADS):
        db.add(Lead(
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
        ))
    db.flush()
    return project
