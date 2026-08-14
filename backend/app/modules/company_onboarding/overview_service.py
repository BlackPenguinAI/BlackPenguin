from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import Lead
from app.modules.users.models import User

from . import services
from .models import CompanyMediaAsset


def serialize_asset(asset: CompanyMediaAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "role": asset.role,
        "name": asset.name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "source_url": asset.source_url,
        "is_primary": asset.is_primary,
        "review_status": asset.review_status,
        "image_url": f"/api/v1/company-onboarding/media/{asset.id}/file",
        "created_at": asset.created_at,
    }


def overview(db: Session, company_id: str) -> dict[str, Any]:
    company = db.query(Company).filter(Company.id == company_id).first()
    profile = services.get_or_create_profile(db, company_id)
    data = profile.profile_data or {}
    projects_query = db.query(Project).filter(Project.company_id == company_id, Project.is_active.is_(True))
    active_projects = projects_query.filter(Project.is_demo.is_(False)).count()
    demo_projects = projects_query.filter(Project.is_demo.is_(True)).count()
    campaigns_query = db.query(ProjectCampaign).join(Project).filter(Project.company_id == company_id)
    leads_query = db.query(Lead).filter(Lead.company_id == company_id)
    users = db.query(User).filter(User.company_id == company_id).all()
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    logo = db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.company_id == company_id,
        CompanyMediaAsset.is_primary.is_(True),
    ).first()
    by_role: dict[str, int] = {}
    for user in users:
        if user.is_active:
            by_role[user.role.value] = by_role.get(user.role.value, 0) + 1
    return {
        "company_id": company_id,
        "name": data.get("preferred_display_name") or data.get("official_company_name") or company.name,
        "legal_name": data.get("legal_company_name") or data.get("official_company_name"),
        "description": data.get("approved_short_company_description"),
        "headquarters": data.get("headquarters"),
        "business_model": data.get("primary_business_model"),
        "asset_classes": data.get("core_asset_classes"),
        "operating_footprint": data.get("current_operating_footprint"),
        "public_contacts": {
            "emails": data.get("public_contact_emails") or [],
            "phones": data.get("public_contact_phones") or [],
            "social_profiles": data.get("corporate_social_profiles") or [],
        },
        "logo_url": serialize_asset(logo)["image_url"] if logo else None,
        "metrics": {
            "active_projects": active_projects,
            "demo_projects": demo_projects,
            "campaigns_total": campaigns_query.count(),
            "campaigns_active": campaigns_query.filter(ProjectCampaign.status == "active").count(),
            "leads_total": leads_query.count(),
            "leads_current_month": leads_query.filter(Lead.created_at >= month_start).count(),
            "team_total": len(users),
            "team_active": sum(user.is_active for user in users),
            "team_by_role": by_role,
        },
        "completion": services.refresh_completion(profile),
        "updated_at": profile.updated_at,
    }
