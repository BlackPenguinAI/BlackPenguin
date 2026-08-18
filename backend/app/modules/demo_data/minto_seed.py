from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.modules.companies.models import Company
from app.modules.company_onboarding import services as company_services
from app.modules.company_onboarding import storage_service as company_storage
from app.modules.company_onboarding.completion import ALL_FIELDS as COMPANY_FIELDS
from app.modules.company_onboarding.models import (
    CompanyMediaAsset,
    CompanyOnboardingProposal,
    CompanyOnboardingSource,
    CompanyProfile,
    OnboardingMessage,
    OnboardingSession,
    ProposalStatus,
    SenderType as CompanySenderType,
    SourceKind,
    SourceStatus,
)
from app.modules.projects import services as project_services
from app.modules.projects import storage_service as project_storage
from app.modules.projects.completion import FIELDS as PROJECT_FIELDS
from app.modules.projects.models import (
    Project,
    ProjectCampaign,
    ProjectMessage,
    ProjectOnboardingProposal,
    ProjectOnboardingSource,
    ProjectProfile,
    ProjectPropertyType,
    ProjectPropertyTypeMedia,
    ProjectProposalStatus,
    ProjectSession,
    ProjectSourceKind,
    ProjectSourceStatus,
    SenderType as ProjectSenderType,
)
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.users.models import User, UserRole

from .minto_manifest import (
    COMPANY_FIELD_OVERRIDES,
    COMPANY_IMAGE,
    COMPANY_PROFILE,
    COMPANY_URL,
    DATASET_VERSION,
    DEMO_GENERATED_PROJECT_FIELDS,
    PROJECT_NOT_APPLICABLE_FIELDS,
    PROJECTS,
)


ASSET_ROOT = Path(__file__).resolve().parent / "assets" / "minto"


def seed_minto_demo(
    db: Session,
    *,
    email: str = "test@minto.com",
    password: str = "1234",
) -> dict[str, Any]:
    """Upsert the isolated Minto demonstration workspace without deleting activity."""
    now = datetime.utcnow()
    plan = _get_or_create_basic_plan(db)
    company, admin = _upsert_company_and_admin(
        db, plan=plan, email=email.strip().casefold(), password=password, now=now,
    )
    _seed_company_onboarding(db, company=company, admin=admin, now=now)
    # A Company named Minto may have been created before this release, when
    # every new tenant automatically received the legacy synthetic project.
    # Preserve its data but keep it out of active demo choices.
    db.query(Project).filter(
        Project.company_id == company.id,
        Project.is_demo.is_(True),
        Project.demo_template_version == "v1",
    ).update({Project.is_active: False}, synchronize_session=False)
    projects = [
        _seed_project(db, company=company, admin=admin, manifest=manifest, now=now)
        for manifest in PROJECTS
    ]
    db.commit()
    return {
        "dataset_version": DATASET_VERSION,
        "company_id": company.id,
        "admin_email": admin.email,
        "projects": [{"id": item.id, "name": item.name} for item in projects],
    }


def _get_or_create_basic_plan(db: Session) -> SubscriptionPlan:
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == "Basic").first()
    if plan:
        return plan
    plan = SubscriptionPlan(
        name="Basic",
        description="Basic Plan",
        max_assistants=1,
        max_mkt_users=5,
        max_sales_users=5,
        max_projects=5,
        max_property_types_per_project=20,
        max_properties_per_project=50,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _upsert_company_and_admin(
    db: Session,
    *,
    plan: SubscriptionPlan,
    email: str,
    password: str,
    now: datetime,
) -> tuple[Company, User]:
    if not email or not password:
        raise ValueError("Minto demo email and password are required.")
    admin = db.query(User).filter(User.email == email).first()
    company = admin.company if admin and admin.company_id else None
    if admin and company and company.name.casefold() != "minto":
        raise ValueError(f"The configured Minto demo email already belongs to Company '{company.name}'.")
    if not company:
        company = db.query(Company).filter(Company.name == "Minto").order_by(Company.created_at).first()
    if not company:
        company = Company(
            name="Minto",
            plan_id=plan.id,
            license_start=now,
            license_end=now + timedelta(days=3650),
            is_active=True,
        )
        db.add(company)
        db.flush()
    company.name = "Minto"
    company.plan_id = plan.id
    company.is_active = True
    if company.license_end is None or company.license_end < now + timedelta(days=365):
        company.license_end = now + timedelta(days=3650)
    if not admin:
        admin = User(email=email, company_id=company.id, role=UserRole.ADMIN)
        db.add(admin)
    admin.company_id = company.id
    admin.first_name = "Minto"
    admin.last_name = "Demo Administrator"
    admin.role = UserRole.ADMIN
    admin.is_active = True
    admin.hashed_password = get_password_hash(password)
    db.flush()
    return company, admin


def _seed_company_onboarding(db: Session, *, company: Company, admin: User, now: datetime) -> None:
    source = db.query(CompanyOnboardingSource).filter(
        CompanyOnboardingSource.company_id == company.id,
        CompanyOnboardingSource.url == COMPANY_URL,
    ).first()
    if not source:
        source = CompanyOnboardingSource(
            company_id=company.id,
            uploaded_by_user_id=admin.id,
            kind=SourceKind.OFFICIAL_WEBSITE,
            status=SourceStatus.READY,
            name="minto.com",
            url=COMPANY_URL,
        )
        db.add(source)
        db.flush()
    source.status = SourceStatus.READY
    source.error_message = None
    source.mime_type = "text/html"
    source.extracted_text = (
        "Minto describes itself as a leading homebuilder, developer, property manager, and investment manager, "
        "with 70 years in operation and more than 100,000 homes built."
    )

    asset = _upsert_company_image(db, company=company, admin=admin, source=source)
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company.id).first()
    if not profile:
        profile = CompanyProfile(company_id=company.id)
        db.add(profile)
        db.flush()

    updates = []
    for key, value in COMPANY_PROFILE.items():
        updates.append({
            "field": key,
            "value": value,
            "status": "confirmed",
            "applicable": True,
            "source_type": "official_company_website",
            "source_reference": COMPANY_URL,
            "confidence": "high",
        })
    for key, config in COMPANY_FIELD_OVERRIDES.items():
        updates.append({
            "field": key,
            "value": config.get("value"),
            "status": config["status"],
            "applicable": config["applicable"],
            "source_type": config["source_type"],
            "source_reference": COMPANY_URL if config["source_type"] == "official_company_website" else DATASET_VERSION,
            "confidence": "high" if config["source_type"] == "official_company_website" else "demo",
        })
    updates.append({
        "field": "company_logo",
        "value": asset.id,
        "status": "confirmed",
        "applicable": True,
        "source_type": "official_company_brand_image",
        "source_reference": COMPANY_IMAGE["source_url"],
        "confidence": "high",
    })
    result = company_services.apply_field_updates(
        db, profile, updates, allow_authoritative_statuses=True, final_approved=True, commit=False,
    )
    if result.rejected:
        raise ValueError(f"Minto Company Profile contains invalid seed fields: {result.rejected}")
    profile.final_approved = True
    company_services.refresh_completion(profile)

    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == company.id).first()
    if not session:
        session = OnboardingSession(company_id=company.id)
        db.add(session)
        db.flush()
    session.is_completed = True
    _ensure_company_message(
        db,
        session,
        CompanySenderType.USER,
        f"Official company website submitted for the demo: {COMPANY_URL}",
    )
    _ensure_company_message(
        db,
        session,
        CompanySenderType.AI,
        "The sourced Minto Company Profile was reviewed and approved for this isolated demonstration workspace.",
    )
    official_keys = set(COMPANY_PROFILE) | {"company_logo", "additional_corporate_languages"}
    for key in official_keys:
        value = asset.id if key == "company_logo" else (
            COMPANY_FIELD_OVERRIDES[key]["value"] if key in COMPANY_FIELD_OVERRIDES else COMPANY_PROFILE[key]
        )
        _upsert_company_proposal(db, source=source, field=key, value=value, admin=admin, now=now)

    # Explicitly evaluate any future Company conditional fields so a manifest
    # upgrade cannot silently leave a seeded profile blocked.
    states = dict(profile.field_states or {})
    for definition in COMPANY_FIELDS:
        states.setdefault(definition.key, {"status": "deferred", "applicable": definition.requirement != "conditionally_required"})
    profile.field_states = states
    company_services.refresh_completion(profile)
    db.add_all([source, profile, session])


def _upsert_company_image(
    db: Session,
    *,
    company: Company,
    admin: User,
    source: CompanyOnboardingSource,
) -> CompanyMediaAsset:
    path = ASSET_ROOT / COMPANY_IMAGE["asset"]
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    asset = db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.company_id == company.id,
        CompanyMediaAsset.sha256 == digest,
    ).first()
    if not asset:
        asset = CompanyMediaAsset(
            company_id=company.id,
            source_id=source.id,
            uploaded_by_user_id=admin.id,
            role="brand_image",
            name=COMPANY_IMAGE["name"],
            mime_type=COMPANY_IMAGE["mime_type"],
            size_bytes=len(content),
            sha256=digest,
            storage_path="pending",
            source_url=COMPANY_IMAGE["source_url"],
            is_primary=True,
            review_status="confirmed",
        )
        db.add(asset)
        db.flush()
    db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.company_id == company.id,
        CompanyMediaAsset.id != asset.id,
    ).update({CompanyMediaAsset.is_primary: False}, synchronize_session=False)
    asset.source_id = source.id
    asset.uploaded_by_user_id = admin.id
    asset.role = "brand_image"
    asset.name = COMPANY_IMAGE["name"]
    asset.mime_type = COMPANY_IMAGE["mime_type"]
    asset.size_bytes = len(content)
    asset.source_url = COMPANY_IMAGE["source_url"]
    asset.is_primary = True
    asset.review_status = "confirmed"
    try:
        stored_path = company_storage.resolve_company_file(asset.storage_path) if asset.storage_path != "pending" else None
    except ValueError:
        stored_path = None
    if stored_path is None or not stored_path.exists():
        stored = company_storage.store_company_file(
            company_id=company.id,
            source_id=asset.id,
            original_filename=path.name,
            content=content,
        )
        asset.storage_path = stored.relative_path
    return asset


def _seed_project(
    db: Session,
    *,
    company: Company,
    admin: User,
    manifest: dict[str, Any],
    now: datetime,
) -> Project:
    project = db.query(Project).filter(
        Project.company_id == company.id,
        Project.demo_template_version == manifest["template_version"],
    ).first()
    if not project:
        project = Project(
            company_id=company.id,
            name=manifest["name"],
            is_active=True,
            is_demo=True,
            demo_template_version=manifest["template_version"],
        )
        db.add(project)
        db.flush()
    project.name = manifest["name"]
    project.is_active = True
    project.is_demo = True
    project.demo_template_version = manifest["template_version"]

    session = project.session or ProjectSession(project_id=project.id)
    if not project.session:
        db.add(session)
        db.flush()
    profile = project.profile or ProjectProfile(project_id=project.id)
    if not project.profile:
        db.add(profile)
        db.flush()

    page_source = _upsert_project_page_source(db, project=project, admin=admin, manifest=manifest)
    images = {
        item["key"]: _upsert_project_image(db, project=project, admin=admin, image=item)
        for item in manifest["images"]
    }
    cover = images["cover"]
    updates = []
    for key, value in manifest["profile"].items():
        generated = key in DEMO_GENERATED_PROJECT_FIELDS
        updates.append({
            "field": key,
            "value": value,
            "status": "confirmed",
            "applicable": True,
            "source_type": "demo_generated" if generated else "official_project_website",
            "source_reference": DATASET_VERSION if generated else manifest["url"],
            "confidence": "demo" if generated else "high",
        })
    updates.append({
        "field": "project_cover",
        "value": cover.id,
        "status": "confirmed",
        "applicable": True,
        "source_type": "official_project_website",
        "source_reference": cover.url,
        "confidence": "high",
    })
    for key in PROJECT_NOT_APPLICABLE_FIELDS:
        updates.append({
            "field": key,
            "value": None,
            "status": "not_applicable",
            "applicable": False,
            "source_type": "demo_generated",
            "source_reference": DATASET_VERSION,
            "confidence": "demo",
        })
    result = project_services.apply_field_updates(
        db, profile, updates, allow_authoritative_statuses=True, commit=False,
    )
    if result.rejected:
        raise ValueError(f"{project.name} contains invalid seed fields: {result.rejected}")

    for definition in PROJECT_FIELDS:
        if definition.key not in (profile.field_states or {}):
            raise ValueError(f"{project.name} seed does not evaluate Project field '{definition.key}'.")
    profile.final_approved = True
    profile.inventory_last_updated_at = now
    profile.approved_for_sales_at = now
    project_services.refresh_completion(profile)
    profile.sales_activation_status = "demo_only"
    project.onboarding_status = "completed"
    project.onboarding_completed_at = now
    project.onboarding_approved_by_user_id = admin.id

    _ensure_project_message(
        db,
        session,
        ProjectSenderType.USER,
        f"Official project website submitted for the demo: {manifest['url']}",
    )
    _ensure_project_message(
        db,
        session,
        ProjectSenderType.AI,
        f"The sourced {project.name} Project Profile was reviewed and approved for simulation.",
    )

    official_fields = set(manifest["profile"]) - DEMO_GENERATED_PROJECT_FIELDS
    official_fields.add("project_cover")
    for key in official_fields:
        value = cover.id if key == "project_cover" else manifest["profile"][key]
        _upsert_project_proposal(db, source=page_source, field=key, value=value, admin=admin, now=now)

    for index, item in enumerate(manifest["property_types"]):
        property_type = db.query(ProjectPropertyType).filter(
            ProjectPropertyType.project_id == project.id,
            ProjectPropertyType.name == item["name"],
        ).first()
        if not property_type:
            property_type = ProjectPropertyType(project_id=project.id, name=item["name"])
            db.add(property_type)
            db.flush()
        property_type.code = item["code"]
        property_type.description = item["description"]
        property_type.bedrooms = item["bedrooms"]
        property_type.bathrooms = item["bathrooms"]
        property_type.area_min = Decimal(str(item["area_min"]))
        property_type.area_max = Decimal(str(item["area_max"]))
        property_type.area_unit = "ft²"
        property_type.total_units = item["total_units"]
        property_type.available_units = item["available_units"]
        property_type.starting_price = Decimal(str(item["starting_price"]))
        property_type.maximum_price = Decimal(str(item["maximum_price"]))
        property_type.currency = "CAD"
        property_type.features = []
        property_type.inventory_updated_at = now
        property_type.images_status = "confirmed"
        property_type.review_status = "confirmed"
        property_type.source_reference = (
            f"{manifest['url']} — product description and area/bedroom evidence; "
            f"{DATASET_VERSION} — DEMO-GENERATED price and inventory."
        )
        property_type.updated_by_user_id = admin.id
        property_type.created_by_user_id = property_type.created_by_user_id or admin.id
        property_type.sort_order = index
        image = images[item["image_key"]]
        media = db.query(ProjectPropertyTypeMedia).filter(
            ProjectPropertyTypeMedia.property_type_id == property_type.id,
            ProjectPropertyTypeMedia.source_id == image.id,
        ).first()
        if not media:
            db.add(ProjectPropertyTypeMedia(
                property_type_id=property_type.id,
                source_id=image.id,
                caption=item["name"],
                sort_order=0,
            ))

    for campaign_data in manifest["campaigns"]:
        campaign = db.query(ProjectCampaign).filter(
            ProjectCampaign.project_id == project.id,
            ProjectCampaign.name == campaign_data["name"],
        ).first()
        if not campaign:
            campaign = ProjectCampaign(project_id=project.id, name=campaign_data["name"])
            db.add(campaign)
        campaign.platform = "demo"
        campaign.objective = campaign_data["objective"]
        campaign.status = "active"
        campaign.external_campaign_id = None
        campaign.lead_form_id = None
        campaign.audience_notes = "Simulation-only campaign for the Minto demonstration workspace."

    db.add_all([project, profile, session, page_source])
    db.flush()
    return project


def _upsert_project_page_source(
    db: Session,
    *,
    project: Project,
    admin: User,
    manifest: dict[str, Any],
) -> ProjectOnboardingSource:
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.kind == ProjectSourceKind.URL,
        ProjectOnboardingSource.url == manifest["url"],
    ).first()
    if not source:
        source = ProjectOnboardingSource(
            project_id=project.id,
            uploaded_by_user_id=admin.id,
            kind=ProjectSourceKind.URL,
            status=ProjectSourceStatus.READY,
            name=manifest["name"],
            url=manifest["url"],
        )
        db.add(source)
        db.flush()
    source.status = ProjectSourceStatus.READY
    source.error_message = None
    source.uploaded_by_user_id = admin.id
    source.name = manifest["name"]
    source.url = manifest["url"]
    source.mime_type = "text/html"
    source.extracted_text = manifest["source_summary"]
    return source


def _upsert_project_image(
    db: Session,
    *,
    project: Project,
    admin: User,
    image: dict[str, Any],
) -> ProjectOnboardingSource:
    path = ASSET_ROOT / image["asset"]
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.sha256 == digest,
    ).first()
    if not source:
        source = ProjectOnboardingSource(
            project_id=project.id,
            uploaded_by_user_id=admin.id,
            kind=ProjectSourceKind.IMAGE,
            status=ProjectSourceStatus.READY,
            name=path.name,
            url=image["source_url"],
            mime_type=image["mime_type"],
            size_bytes=len(content),
            sha256=digest,
            original_filename=path.name,
            extracted_text="[Official Minto project image retained for the demo]",
        )
        db.add(source)
        db.flush()
    source.status = ProjectSourceStatus.READY
    source.error_message = None
    source.uploaded_by_user_id = admin.id
    source.name = path.name
    source.url = image["source_url"]
    source.mime_type = image["mime_type"]
    source.size_bytes = len(content)
    source.sha256 = digest
    source.original_filename = path.name
    source.extracted_text = "[Official Minto project image retained for the demo]"
    source.is_primary = bool(image.get("primary"))
    if source.is_primary:
        db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.project_id == project.id,
            ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE,
            ProjectOnboardingSource.id != source.id,
        ).update({ProjectOnboardingSource.is_primary: False}, synchronize_session=False)
    try:
        stored_path = project_storage.resolve_project_file(source.storage_path) if source.storage_path else None
    except ValueError:
        stored_path = None
    if stored_path is None or not stored_path.exists():
        stored = project_storage.store_project_file(
            company_id=project.company_id,
            project_id=project.id,
            source_id=source.id,
            original_filename=path.name,
            content=content,
        )
        source.storage_path = stored.relative_path
        source.stored_filename = stored.stored_filename
    return source


def _ensure_company_message(
    db: Session,
    session: OnboardingSession,
    sender: CompanySenderType,
    content: str,
) -> None:
    if not db.query(OnboardingMessage).filter(
        OnboardingMessage.session_id == session.id,
        OnboardingMessage.content == content,
    ).first():
        db.add(OnboardingMessage(session_id=session.id, sender=sender, content=content))


def _ensure_project_message(
    db: Session,
    session: ProjectSession,
    sender: ProjectSenderType,
    content: str,
) -> None:
    if not db.query(ProjectMessage).filter(
        ProjectMessage.session_id == session.id,
        ProjectMessage.content == content,
    ).first():
        db.add(ProjectMessage(session_id=session.id, sender=sender, content=content))


def _upsert_company_proposal(
    db: Session,
    *,
    source: CompanyOnboardingSource,
    field: str,
    value: Any,
    admin: User,
    now: datetime,
) -> None:
    proposal = db.query(CompanyOnboardingProposal).filter(
        CompanyOnboardingProposal.source_id == source.id,
        CompanyOnboardingProposal.field_key == field,
    ).first()
    if not proposal:
        proposal = CompanyOnboardingProposal(source_id=source.id, field_key=field)
        db.add(proposal)
    proposal.value = value
    proposal.evidence = f"Curated from the official Minto website for {DATASET_VERSION}."
    proposal.confidence = "high"
    proposal.status = ProposalStatus.CONFIRMED
    proposal.reviewed_by_user_id = admin.id
    proposal.reviewed_at = now


def _upsert_project_proposal(
    db: Session,
    *,
    source: ProjectOnboardingSource,
    field: str,
    value: Any,
    admin: User,
    now: datetime,
) -> None:
    proposal = db.query(ProjectOnboardingProposal).filter(
        ProjectOnboardingProposal.source_id == source.id,
        ProjectOnboardingProposal.field_key == field,
    ).first()
    if not proposal:
        proposal = ProjectOnboardingProposal(source_id=source.id, field_key=field)
        db.add(proposal)
    proposal.value = value
    proposal.evidence = f"Curated from {source.url} for {DATASET_VERSION}."
    proposal.confidence = "high"
    proposal.status = ProjectProposalStatus.CONFIRMED
    proposal.reviewed_by_user_id = admin.id
    proposal.reviewed_at = now
