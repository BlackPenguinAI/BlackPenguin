from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Request
from sqlalchemy import func, text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.companies.models import Company
from app.modules.sales_agent.models import SalesConversation, SalesFollowUpJob, SalesMessage
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.projects.models import Project
from app.integrations.transactional_email import send_appointment_email
from app.modules.system_settings.models import LegalDocument
from app.modules.users.models import User, UserRole
from app.modules.users.project_access import project_ids_for_user

from .models import (
    AgentOperatingPolicy, ConversationKpiTarget, DataExportAuditEvent,
    AppointmentEmailOutbox, HumanInterventionCase, KnowledgeGuidanceItem, LegalDocumentVersion,
    Notification, NotificationOutbox, PlatformAuditEvent, UserLegalAcceptance,
)


LEGAL_TYPES = ("privacy", "terms", "data_deletion")
HUMAN_REQUEST = re.compile(
    r"\b(human|person|advisor|sales(?:person)?|agent|representative|asesor(?:a)?|humano|persona|vendedor(?:a)?)\b",
    re.IGNORECASE,
)
HUMAN_VERB = re.compile(r"\b(talk|speak|call|contact|transfer|quiero|hablar|llam|comunicar|pas[ae])\w*\b", re.IGNORECASE)
LEGAL_REQUEST = re.compile(
    r"\b(legal|lawyer|lawsuit|contract clause|tax advice|abogado|demanda|cl[aá]usula|asesor[ií]a legal|impuesto)\b",
    re.IGNORECASE,
)
NEGOTIATION_REQUEST = re.compile(
    r"\b(exception|special discount|negotiate|counteroffer|custom terms|excepci[oó]n|descuento especial|negociar|contraoferta|t[eé]rminos especiales)\b",
    re.IGNORECASE,
)


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _digest(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256((settings.SECRET_KEY + ":" + value).encode()).hexdigest()


def request_fingerprint(request: Request | None) -> tuple[str | None, str | None, str | None]:
    if request is None:
        return None, None, None
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else None)
    return _digest(ip), _digest(request.headers.get("user-agent")), request.headers.get("x-request-id")


def assert_company_license(db: Session, user: User, *, now: datetime | None = None) -> None:
    if user.role == UserRole.SUPERADMIN:
        return
    company = db.query(Company).filter(Company.id == user.company_id).first()
    support = settings.SUPPORT_EMAIL
    if not company or not company.is_active:
        raise HTTPException(status_code=403, detail={
            "code": "COMPANY_SUSPENDED",
            "message": f"Your Company access is suspended. Contact Black Penguin support at {support}.",
            "support_email": support,
        })
    current = now or datetime.utcnow()
    if company.license_start and current < company.license_start:
        raise HTTPException(status_code=403, detail={
            "code": "COMPANY_LICENSE_NOT_STARTED",
            "message": f"Your Company license has not been activated yet. Contact Black Penguin support at {support}.",
            "support_email": support,
        })
    if company.license_end and current >= company.license_end:
        raise HTTPException(status_code=403, detail={
            "code": "COMPANY_LICENSE_EXPIRED",
            "message": f"Your Company license has expired. Contact Black Penguin support at {support}.",
            "support_email": support,
        })


def published_legal_versions(db: Session, *, language: str = "en") -> dict[str, LegalDocumentVersion]:
    result: dict[str, LegalDocumentVersion] = {}
    for doc_type in LEGAL_TYPES:
        document = db.query(LegalDocument).filter(
            LegalDocument.doc_type == doc_type, LegalDocument.language == language,
        ).first()
        if not document:
            # Legal pages already have safe system defaults. Materialize those
            # defaults before snapshotting so a fresh installation can activate
            # its first invited user without a manual seed step.
            from app.modules.system_settings.services import get_legal_document
            document = get_legal_document(db, doc_type, language)
        content_hash = hashlib.sha256(document.content_markdown.encode()).hexdigest()
        version = db.query(LegalDocumentVersion).filter(
            LegalDocumentVersion.doc_type == doc_type,
            LegalDocumentVersion.language == language,
            LegalDocumentVersion.content_hash == content_hash,
        ).order_by(LegalDocumentVersion.version.desc()).first()
        if not version:
            latest = db.query(func.max(LegalDocumentVersion.version)).filter(
                LegalDocumentVersion.doc_type == doc_type,
                LegalDocumentVersion.language == language,
            ).scalar() or 0
            version = LegalDocumentVersion(
                doc_type=doc_type, language=language, version=latest + 1,
                content_hash=content_hash, content_markdown=document.content_markdown,
            )
            db.add(version); db.flush()
        result[doc_type] = version
    return result


def legal_version_payload(versions: dict[str, LegalDocumentVersion]) -> list[dict]:
    paths = {"privacy": "/legal/privacy", "terms": "/legal/terms", "data_deletion": "/legal/data-deletion"}
    return [{
        "doc_type": item.doc_type, "version_id": item.id, "version": item.version,
        "content_hash": item.content_hash, "url": paths[item.doc_type],
    } for item in versions.values()]


def record_legal_acceptance(
    db: Session, *, user: User, invitation_id: str | None, accepted_version_ids: dict[str, str],
    request: Request | None,
) -> UserLegalAcceptance:
    versions = published_legal_versions(db)
    expected = {key: value.id for key, value in versions.items()}
    if accepted_version_ids != expected:
        raise HTTPException(status_code=409, detail={
            "code": "LEGAL_DOCUMENT_VERSION_CHANGED",
            "message": "One or more legal documents changed. Review and accept the current versions.",
            "legal_documents": legal_version_payload(versions),
        })
    existing = db.query(UserLegalAcceptance).filter(
        UserLegalAcceptance.user_id == user.id,
        UserLegalAcceptance.invitation_id == invitation_id,
    ).first()
    if existing:
        return existing
    ip_hash, user_agent_hash, _ = request_fingerprint(request)
    acceptance = UserLegalAcceptance(
        user_id=user.id, company_id=user.company_id, invitation_id=invitation_id,
        privacy_version_id=versions["privacy"].id,
        terms_version_id=versions["terms"].id,
        data_deletion_version_id=versions["data_deletion"].id,
        ip_hash=ip_hash, user_agent_hash=user_agent_hash,
    )
    db.add(acceptance); db.flush()
    return acceptance


def _chain_hash(previous_hash: str | None, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{previous_hash or ''}.{canonical}".encode()).hexdigest()


def _lock_audit_chain(db: Session, *, stream: str, company_id: str | None) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtext(:chain_key))"),
            {"chain_key": f"{stream}:{company_id or 'platform'}"},
        )


def record_platform_event(
    db: Session, *, actor: User | None, event_type: str, entity_type: str | None = None,
    entity_id: str | None = None, company_id: str | None = None, reason: str | None = None,
    payload: dict | None = None, request: Request | None = None,
) -> PlatformAuditEvent:
    scope_company_id = company_id or (actor.company_id if actor else None)
    _lock_audit_chain(db, stream="platform", company_id=scope_company_id)
    previous = db.query(PlatformAuditEvent).filter(
        PlatformAuditEvent.company_id == scope_company_id,
    ).order_by(PlatformAuditEvent.created_at.desc(), PlatformAuditEvent.id.desc()).first()
    ip_hash, _, request_id = request_fingerprint(request)
    values = {
        "company_id": scope_company_id,
        "actor_user_id": actor.id if actor else None, "actor_role": _role(actor) if actor else None,
        "event_type": event_type, "entity_type": entity_type, "entity_id": entity_id,
        "reason": reason, "payload": payload or {}, "request_id": request_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    event = PlatformAuditEvent(
        company_id=values["company_id"], actor_user_id=values["actor_user_id"],
        actor_role=values["actor_role"], event_type=event_type, entity_type=entity_type,
        entity_id=entity_id, reason=reason, payload_json=payload or {}, request_id=request_id,
        ip_hash=ip_hash, previous_hash=previous.event_hash if previous else None,
        event_hash=_chain_hash(previous.event_hash if previous else None, values),
    )
    db.add(event); db.flush()
    return event


def record_export_event(
    db: Session, *, actor: User, export_type: str, filters: dict, record_count: int,
    content: bytes, request: Request | None = None,
) -> DataExportAuditEvent:
    _lock_audit_chain(db, stream="export", company_id=actor.company_id)
    previous = db.query(DataExportAuditEvent).filter(
        DataExportAuditEvent.company_id == actor.company_id,
    ).order_by(DataExportAuditEvent.created_at.desc(), DataExportAuditEvent.id.desc()).first()
    ip_hash, _, request_id = request_fingerprint(request)
    content_hash = hashlib.sha256(content).hexdigest()
    values = {
        "company_id": actor.company_id, "actor_user_id": actor.id, "actor_role": _role(actor),
        "export_type": export_type, "filters": filters, "record_count": record_count,
        "content_hash": content_hash, "outcome": "generated", "request_id": request_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    event = DataExportAuditEvent(
        company_id=actor.company_id, actor_user_id=actor.id, actor_role=_role(actor),
        export_type=export_type, filters_json=filters, record_count=record_count,
        content_hash=content_hash, outcome="generated", request_id=request_id, ip_hash=ip_hash,
        previous_hash=previous.event_hash if previous else None,
        event_hash=_chain_hash(previous.event_hash if previous else None, values),
    )
    db.add(event); db.flush()
    return event


def _validate_windows(windows: dict[str, list[dict[str, str]]]) -> None:
    for day, values in windows.items():
        if day not in {str(item) for item in range(7)}:
            raise HTTPException(status_code=422, detail="Operating schedule days must be 0 (Monday) through 6 (Sunday).")
        for item in values:
            try:
                start, end = time.fromisoformat(item["start"]), time.fromisoformat(item["end"])
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(status_code=422, detail="Every operating window requires valid start and end times.") from exc
            if end <= start:
                raise HTTPException(status_code=422, detail="Operating window end time must be after start time.")


def upsert_operating_policy(db: Session, *, user: User, payload) -> AgentOperatingPolicy:
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    _validate_windows(payload.weekly_windows)
    try:
        for value in payload.blackout_dates:
            date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Blackout dates must use YYYY-MM-DD format.") from exc
    query = db.query(AgentOperatingPolicy).filter(
        AgentOperatingPolicy.company_id == user.company_id,
        AgentOperatingPolicy.project_id == payload.project_id,
    )
    policy = query.first() or AgentOperatingPolicy(company_id=user.company_id, project_id=payload.project_id)
    for key, value in payload.model_dump().items():
        setattr(policy, key, value)
    policy.updated_by_user_id = user.id
    db.add(policy); db.commit(); db.refresh(policy)
    return policy


def operating_policy_for(db: Session, *, company_id: str, project_id: str | None) -> AgentOperatingPolicy | None:
    if project_id:
        item = db.query(AgentOperatingPolicy).filter(
            AgentOperatingPolicy.company_id == company_id,
            AgentOperatingPolicy.project_id == project_id,
        ).first()
        if item:
            return item
    return db.query(AgentOperatingPolicy).filter(
        AgentOperatingPolicy.company_id == company_id,
        AgentOperatingPolicy.project_id.is_(None),
    ).first()


def next_allowed_proactive_time(
    db: Session, *, company_id: str, project_id: str | None, now: datetime | None = None,
) -> datetime:
    policy = operating_policy_for(db, company_id=company_id, project_id=project_id)
    current_utc = now or datetime.utcnow()
    if not policy or not policy.is_enabled:
        return current_utc
    zone = ZoneInfo(policy.timezone)
    local_now = current_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    blackout = set(policy.blackout_dates or [])
    for offset in range(0, 15):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.isoformat() in blackout:
            continue
        windows = (policy.weekly_windows or {}).get(str(candidate_date.weekday()), [])
        for window in sorted(windows, key=lambda item: item["start"]):
            start_local = datetime.combine(candidate_date, time.fromisoformat(window["start"]), tzinfo=zone)
            end_local = datetime.combine(candidate_date, time.fromisoformat(window["end"]), tzinfo=zone)
            if offset == 0 and start_local <= local_now < end_local:
                return current_utc
            if start_local > local_now:
                return start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    raise HTTPException(status_code=409, detail={
        "code": "NO_OPERATING_WINDOW",
        "message": "No permitted proactive contact window is configured in the next 14 days.",
    })


def escalation_reason(text: str) -> str | None:
    if HUMAN_REQUEST.search(text) and HUMAN_VERB.search(text):
        return "HUMAN_REQUESTED"
    if LEGAL_REQUEST.search(text):
        return "LEGAL_QUESTION"
    if NEGOTIATION_REQUEST.search(text):
        return "COMPLEX_NEGOTIATION"
    return None


def enqueue_notification(
    db: Session, *, company_id: str | None, project_id: str | None, event_type: str,
    entity_type: str | None, entity_id: str | None, payload: dict, dedupe_key: str,
) -> NotificationOutbox:
    existing = db.query(NotificationOutbox).filter(NotificationOutbox.dedupe_key == dedupe_key).first()
    if existing:
        return existing
    item = NotificationOutbox(
        company_id=company_id, project_id=project_id, event_type=event_type,
        entity_type=entity_type, entity_id=entity_id, payload_json=payload,
        dedupe_key=dedupe_key,
    )
    db.add(item); db.flush()
    return item


def enqueue_appointment_emails(
    db: Session, *, company_id: str, meeting_id: str,
    lead_email: str | None, sales_email: str | None,
) -> list[AppointmentEmailOutbox]:
    queued: list[AppointmentEmailOutbox] = []
    for kind, recipient in (("lead", lead_email), ("sales", sales_email)):
        if not recipient:
            continue
        key = f"appointment-email:{meeting_id}:{kind}:{recipient.strip().casefold()}"
        existing = db.query(AppointmentEmailOutbox).filter(AppointmentEmailOutbox.dedupe_key == key).first()
        if existing:
            queued.append(existing); continue
        item = AppointmentEmailOutbox(
            company_id=company_id, meeting_id=meeting_id,
            recipient_email=recipient.strip().casefold(), recipient_kind=kind,
            dedupe_key=key,
        )
        db.add(item); queued.append(item)
    db.flush()
    return queued


def _appointment_ics(meeting: Meeting, project: Project) -> str:
    end = meeting.meeting_time + timedelta(minutes=meeting.duration_minutes)
    stamp = lambda value: value.strftime("%Y%m%dT%H%M%SZ")
    location = ", ".join(value for value in (project.name, project.address, project.city, project.country) if value).replace(",", "\\,")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Black Penguin//Appointment//EN",
        "BEGIN:VEVENT", f"UID:{meeting.id}@blackpenguin.ai", f"DTSTAMP:{stamp(datetime.utcnow())}",
        f"DTSTART:{stamp(meeting.meeting_time)}", f"DTEND:{stamp(end)}",
        f"SUMMARY:{project.name} property visit", f"LOCATION:{location}",
        "DESCRIPTION:Appointment coordinated by Black Penguin AI Sales Agent.",
        "END:VEVENT", "END:VCALENDAR", "",
    ])


def process_appointment_email_outbox(db: Session, *, limit: int = 10) -> int:
    query = db.query(AppointmentEmailOutbox).filter(
        AppointmentEmailOutbox.status == "pending",
        AppointmentEmailOutbox.attempts < 5,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    sent = 0
    for item in query.order_by(AppointmentEmailOutbox.created_at).limit(limit).all():
        meeting = db.query(Meeting).filter(Meeting.id == item.meeting_id).first()
        project = db.query(Project).filter(Project.id == meeting.project_id).first() if meeting else None
        lead = db.query(Lead).filter(Lead.id == meeting.lead_id).first() if meeting else None
        sales = db.query(User).filter(User.id == meeting.assigned_sales_user_id).first() if meeting and meeting.assigned_sales_user_id else None
        if not meeting or not project or not lead:
            item.status = "failed"; item.last_error = "appointment_context_missing"; item.attempts += 1
            continue
        try:
            zone = ZoneInfo(project.timezone or "UTC")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local_time = meeting.meeting_time.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
        sales_name = " ".join(filter(None, [sales.first_name, sales.last_name])) if sales else "the assigned Sales representative"
        location = ", ".join(value for value in (project.name, project.address, project.city, project.country) if value)
        subject = f"Appointment confirmed · {project.name}"
        body = (
            f"Your property appointment is confirmed.\n\n"
            f"Lead: {lead.full_name}\nSales representative: {sales_name}\n"
            f"Date and time: {local_time.strftime('%A, %B %d, %Y at %I:%M %p')} ({project.timezone or 'UTC'})\n"
            f"Location: {location}\n\nThis email was generated by Black Penguin."
        )
        try:
            send_appointment_email(
                recipient=item.recipient_email, subject=subject, body=body,
                ics_content=_appointment_ics(meeting, project),
            )
            item.status = "sent"; item.sent_at = datetime.utcnow(); item.last_error = None; sent += 1
        except Exception as exc:
            item.last_error = type(exc).__name__; item.attempts += 1
            if item.attempts >= 5:
                item.status = "failed"
    db.commit()
    return sent


def process_notification_outbox(db: Session, *, company_id: str | None = None) -> int:
    query = db.query(NotificationOutbox).filter(NotificationOutbox.status == "pending")
    if company_id:
        query = query.filter(NotificationOutbox.company_id == company_id)
    created = 0
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    for event in query.order_by(NotificationOutbox.created_at).limit(100).all():
        users = db.query(User).filter(
            User.company_id == event.company_id,
            User.is_active.is_(True), User.deleted_at.is_(None),
            User.role.in_([UserRole.ADMIN, UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES]),
        ).all()
        lead = db.query(Lead).filter(Lead.id == event.entity_id).first() if event.entity_type == "lead" else None
        payload = event.payload_json or {}
        recipient_roles = {str(role) for role in payload.get("recipient_roles", []) if role}
        for user in users:
            role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
            if recipient_roles and role_value not in recipient_roles:
                continue
            if user.role == UserRole.SALES and (not lead or lead.assigned_sales_user_id != user.id):
                continue
            if event.project_id and user.role in {UserRole.MKT, UserRole.SALES}:
                allowed = project_ids_for_user(db, user)
                if (user.project_access_scope or "all") == "selected" and event.project_id not in allowed:
                    continue
            if event.event_type == "human_intervention" and user.role == UserRole.MKT:
                continue
            dedupe = f"{event.dedupe_key}:{user.id}"
            if db.query(Notification).filter(
                Notification.recipient_user_id == user.id, Notification.dedupe_key == dedupe,
            ).first():
                continue
            db.add(Notification(
                company_id=event.company_id, project_id=event.project_id,
                recipient_user_id=user.id, notification_type=event.event_type,
                severity="warning" if event.event_type == "human_intervention" else "info",
                title=str(payload.get("title") or event.event_type.replace("_", " ").title()),
                body=str(payload.get("body") or "A new event requires your attention."),
                entity_type=event.entity_type, entity_id=event.entity_id,
                action_url=payload.get("action_url") or (f"/app/leads?lead={event.entity_id}" if event.entity_type == "lead" else None),
                dedupe_key=dedupe,
            ))
            created += 1
        event.status = "processed"; event.processed_at = datetime.utcnow(); event.attempts += 1
    db.commit()
    return created


def create_intervention_case(
    db: Session, *, conversation: SalesConversation, lead: Lead, reason: str,
    evidence: str | None = None, confidence: str | None = None,
) -> HumanInterventionCase:
    dedupe_key = f"{reason}:open"
    existing = db.query(HumanInterventionCase).filter(
        HumanInterventionCase.conversation_id == conversation.id,
        HumanInterventionCase.dedupe_key == dedupe_key,
        HumanInterventionCase.status == "open",
    ).first()
    if existing:
        return existing
    case = HumanInterventionCase(
        company_id=conversation.company_id, project_id=conversation.project_id,
        lead_id=lead.id, conversation_id=conversation.id, reason=reason,
        evidence=evidence, confidence=confidence, dedupe_key=dedupe_key,
    )
    conversation.is_paused = True
    conversation.pause_reason = f"Human intervention: {reason}"
    lead.agent_status = "human_control"
    lead.pipeline_stage = "S09_HANDOFF"
    lead.next_action_at = None
    db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == conversation.id,
        SalesFollowUpJob.status.in_(["pending", "processing"]),
    ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
    db.add(case)
    enqueue_notification(
        db, company_id=conversation.company_id, project_id=conversation.project_id,
        event_type="human_intervention", entity_type="lead", entity_id=lead.id,
        payload={"title": "Human intervention required", "body": f"{lead.full_name}: {reason.replace('_', ' ').title()}", "reason": reason},
        dedupe_key=f"human-intervention:{case.id}",
    )
    db.flush()
    return case


def guidance_context(db: Session, *, company_id: str, project_id: str | None, limit: int = 20) -> list[dict]:
    query = db.query(KnowledgeGuidanceItem).filter(
        KnowledgeGuidanceItem.company_id == company_id,
        KnowledgeGuidanceItem.status == "approved",
    )
    if project_id:
        query = query.filter(
            (KnowledgeGuidanceItem.project_id == project_id) | (KnowledgeGuidanceItem.project_id.is_(None))
        )
    else:
        query = query.filter(KnowledgeGuidanceItem.project_id.is_(None))
    return [{"kind": row.kind, "title": row.title, "content": row.content, "scope": "project" if row.project_id else "company"}
            for row in query.order_by(KnowledgeGuidanceItem.project_id.is_(None), KnowledgeGuidanceItem.updated_at.desc()).limit(limit)]


def kpi_snapshot(db: Session, *, company_id: str, project_id: str | None = None) -> dict:
    leads = db.query(Lead).filter(Lead.company_id == company_id, Lead.deleted_at.is_(None), Lead.is_demo.is_(False), Lead.is_test.is_(False))
    conversations = db.query(SalesConversation).filter(SalesConversation.company_id == company_id)
    if project_id:
        leads = leads.filter(Lead.project_id == project_id)
        conversations = conversations.filter(SalesConversation.project_id == project_id)
    conversation_ids = [row[0] for row in conversations.with_entities(SalesConversation.id).all()]
    contacted = leads.filter(Lead.last_interaction_at.isnot(None)).count()
    responded = 0
    turns: list[int] = []
    if conversation_ids:
        rows = db.query(SalesMessage.conversation_id, SalesMessage.direction, func.count(SalesMessage.id)).filter(
            SalesMessage.conversation_id.in_(conversation_ids), SalesMessage.status != "failed",
        ).group_by(SalesMessage.conversation_id, SalesMessage.direction).all()
        grouped: dict[str, dict[str, int]] = {}
        for conversation_id, direction, count in rows:
            grouped.setdefault(conversation_id, {})[direction] = count
        responded = sum(1 for value in grouped.values() if value.get("inbound", 0) > 0)
        turns = [sum(value.values()) for value in grouped.values() if value.get("inbound", 0) > 0]
    target = db.query(ConversationKpiTarget).filter(
        ConversationKpiTarget.company_id == company_id,
        ConversationKpiTarget.project_id == project_id,
    ).first()
    return {
        "contacted_leads": contacted, "responded_leads": responded,
        "response_rate_percent": round(responded * 100 / contacted, 1) if contacted else 0,
        "average_conversation_turns": round(sum(turns) / len(turns), 1) if turns else 0,
        "sample_size": len(turns),
        "target": ({
            "response_rate_percent": target.response_rate_percent,
            "conversation_turns_min": target.conversation_turns_min,
            "conversation_turns_max": target.conversation_turns_max,
        } if target else None),
    }
