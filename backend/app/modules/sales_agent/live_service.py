"""Production SMS workflow sharing the same LangGraph and CRM services as simulation."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.integrations.messaging_gateway import channel_sender, company_live_channel, default_provider, live_provider, send_message, send_sms
from app.modules.projects import asset_share_service
from app.modules.projects.models import Project, ProjectCampaign, ProjectSalesAsset, SalesAssetShare
from app.modules.sales_crm.intelligence import merge_extracted_facts, update_lead_intelligence
from app.modules.sales_crm.models import FunnelStage, Lead, LeadContact

from .graph import GRAPH_VERSION, TOOLSET_VERSION, build_sales_graph
from .conversation_scope import scoped_messages_query
from .response_policy import AFFIRMATIVE, action_types, requested_topics
from .models import (
    AgentRun, ExternalWebhookEvent, OutboundMessage, SalesConversation, SalesConversationLeadContext, SalesInboundJob,
    SalesFollowUpJob, SalesMessage,
)
from .service import (
    _appointment_confirmation, _availability_reply,
    _confirm_or_request_location, _is_availability_request, _offered_slot_selection, _project_zone,
    _recent_appointment_context, get_or_create_conversation,
)
from app.modules.sales_crm.scheduling import create_agent_appointment, next_cadence_time
from app.modules.ai_core.services import get_ai_config
from app.modules.governance.services import (
    create_intervention_case, escalation_reason, next_allowed_proactive_time,
    operating_policy_for,
)
from app.core.config import settings
from app.integrations.whatsapp_templates import (
    initial_template_parameters,
    render_initial_template,
    validate_initial_template,
)


EXPLICIT_ASSET_SHARE = re.compile(
    r"\b(?:send|share|give|download|can i get|could i get|email me|"
    r"env[ií]a|comparte|m[aá]ndame|puedo (?:tener|recibir|descargar))\b",
    re.IGNORECASE,
)


def normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return f"+{digits}"


def _confirmed_handoff_reply(inbound_text: str, actions: list[dict]) -> str:
    """Confirm only the durable intervention created by the runtime."""
    requested = action_types(actions)
    if "request_callback" in requested:
        return (
            "I’ve sent your callback request to the Sales team with this conversation context. "
            "A team member will review it and follow up."
        )
    material_terms = ("brochure", "floor plan", "blueprint", "price list", "email", "document")
    if any(term in (inbound_text or "").casefold() for term in material_terms):
        return (
            "I don’t currently have an approved document available to share here. "
            "I’ve asked the Sales team to review your request and follow up."
        )
    return (
        "I’ve sent your request and this conversation context for human review. "
        "A Sales team member will follow up."
    )


def ensure_contact(db: Session, lead: Lead) -> LeadContact:
    phone = normalize_phone(lead.phone)
    contact = db.query(LeadContact).filter(
        LeadContact.company_id == lead.company_id,
        LeadContact.canonical_phone == phone,
    ).first()
    if not contact:
        contact = LeadContact(
            company_id=lead.company_id, canonical_phone=phone,
            full_name=lead.full_name, email=lead.email,
            preferred_channel=lead.preferred_channel or "sms",
        )
        db.add(contact); db.flush()
    normalized_db_phone = Lead.phone
    for character in ("+", " ", "-", "(", ")"):
        normalized_db_phone = func.replace(normalized_db_phone, character, "")
    prior_leads = db.query(Lead).filter(
        Lead.company_id == lead.company_id,
        Lead.id != lead.id,
        normalized_db_phone == phone.removeprefix("+"),
    ).order_by(Lead.created_at.desc()).limit(20).all()
    matching = prior_leads
    contact.full_name = lead.full_name or contact.full_name
    contact.email = lead.email or contact.email
    contact.previous_projects = [
        {
            "lead_id": item.id, "project_id": item.project_id,
            "segment": item.assigned_segment, "intent_tier": item.intent_tier,
            "qualification_summary": item.qualification_summary,
            "last_interaction_at": item.last_interaction_at.isoformat() if item.last_interaction_at else None,
        }
        for item in matching
    ]
    lead.contact_id = contact.id
    db.add_all([contact, lead])
    return contact


def get_or_create_live_conversation(db: Session, lead: Lead, *, provider: str | None = None) -> tuple[SalesConversation, bool]:
    # A provider switch affects only new threads. A lead that already owns a
    # physical SMS conversation must keep its original sender and webhook path.
    channel = lead.preferred_channel or "sms"
    pinned = db.query(SalesConversation).filter(
        SalesConversation.lead_id == lead.id,
        SalesConversation.channel == channel,
    ).first()
    if pinned:
        return pinned, False
    provider = provider or default_provider(db)
    sender = channel_sender(db, provider=provider, company_id=lead.company_id, channel=channel)
    thread_key = (
        f"{provider}:{normalize_phone(sender)}:{normalize_phone(lead.phone)}"
        if channel == "sms" else
        f"{provider}:{channel}:{normalize_phone(sender)}:{normalize_phone(lead.phone)}"
    )
    existing = db.query(SalesConversation).filter(
        SalesConversation.provider_thread_key == thread_key,
    ).first()
    if existing:
        if existing.company_id != lead.company_id:
            raise HTTPException(
                status_code=409,
                detail="This phone is already assigned to another Company on the shared SMS sender. The conversation was not reassigned.",
            )
        current_context = db.query(SalesConversationLeadContext).filter(
            SalesConversationLeadContext.conversation_id == existing.id,
            SalesConversationLeadContext.lead_id == existing.lead_id,
        ).first()
        if not current_context:
            db.add(SalesConversationLeadContext(
                conversation_id=existing.id, lead_id=existing.lead_id, is_active=True,
            ))
        if existing.lead_id != lead.id:
            db.query(SalesFollowUpJob).filter(
                SalesFollowUpJob.conversation_id == existing.id,
                SalesFollowUpJob.status == "pending",
            ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
            db.query(SalesConversationLeadContext).filter(
                SalesConversationLeadContext.conversation_id == existing.id,
                SalesConversationLeadContext.is_active.is_(True),
            ).update({SalesConversationLeadContext.is_active: False}, synchronize_session=False)
            context = db.query(SalesConversationLeadContext).filter(
                SalesConversationLeadContext.conversation_id == existing.id,
                SalesConversationLeadContext.lead_id == lead.id,
            ).first()
            if not context:
                context = SalesConversationLeadContext(conversation_id=existing.id, lead_id=lead.id)
            context.is_active = True
            context.activated_at = datetime.utcnow()
            db.add(context)
            existing.lead_id = lead.id
            existing.project_id = lead.project_id
            existing.campaign_id = lead.campaign_id
            existing.stage = "new"
            existing.is_paused = False
            existing.pause_reason = None
            existing.updated_at = datetime.utcnow()
            db.add(existing); db.flush()
            return existing, True
        return existing, False
    conversation = SalesConversation(
        company_id=lead.company_id, project_id=lead.project_id, campaign_id=lead.campaign_id,
        lead_id=lead.id, channel=channel, provider=provider, provider_thread_key=thread_key,
        automation_level=2, is_paused=False,
    )
    db.add(conversation); db.flush()
    db.add(SalesConversationLeadContext(conversation_id=conversation.id, lead_id=lead.id, is_active=True))
    db.flush()
    return conversation, True


def resolve_inbound_conversation(db: Session, *, provider: str = "twilio", channel: str = "sms", to_number: str, from_number: str) -> SalesConversation | None:
    key = (
        f"{provider}:{normalize_phone(to_number)}:{normalize_phone(from_number)}"
        if channel == "sms" else
        f"{provider}:{channel}:{normalize_phone(to_number)}:{normalize_phone(from_number)}"
    )
    return db.query(SalesConversation).filter(SalesConversation.provider_thread_key == key).first()


def _initial_message(lead: Lead, project: Project, campaign: ProjectCampaign | None) -> str:
    first_name = (lead.full_name or "there").split()[0]
    source = campaign.name if campaign else project.name
    return (
        f"Hi {first_name}, thanks for your interest in {source}. I'm Black Penguin's AI Sales Agent for "
        f"{project.name}. I can answer questions, help you compare the available options and coordinate a visit. "
        "What would be most useful to know first? Reply STOP to opt out."
    )


def _whatsapp_customer_window_open(db: Session, conversation: SalesConversation) -> bool:
    """WhatsApp free-form replies are allowed for 24 hours after an inbound message."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return db.query(SalesMessage.id).filter(
        SalesMessage.conversation_id == conversation.id,
        SalesMessage.channel == "whatsapp",
        SalesMessage.direction == "inbound",
        SalesMessage.created_at >= cutoff,
    ).first() is not None


async def _dispatch(
    db: Session, *, conversation: SalesConversation, lead: Lead, content: str,
    role: str, agent_run_id: str | None, author_user_id: str | None = None,
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> SalesMessage:
    message_metadata = dict(metadata or {})
    message_metadata.setdefault("lead_id", lead.id)
    message_metadata.setdefault("project_id", conversation.project_id)
    event_kind = message_metadata.get("event_kind")
    uses_whatsapp_template = event_kind in {"meta_lead_first_contact", "manual_lead_first_contact"}
    persisted_content = content
    template_parameters = None
    if conversation.channel == "whatsapp" and uses_whatsapp_template:
        from app.modules.system_settings.services import get_telnyx_company_config

        company_config = get_telnyx_company_config(db, conversation.company_id)
        template_name = company_config.whatsapp_template_name if company_config else None
        template_language = company_config.whatsapp_template_language if company_config else None
        template_content = company_config.whatsapp_template_content if company_config else None
        project = db.query(Project).filter(
            Project.id == conversation.project_id,
            Project.company_id == conversation.company_id,
        ).first()
        if not company_config or not template_name:
            raise HTTPException(status_code=409, detail="The Company does not have an initial WhatsApp template configured.")
        try:
            validate_initial_template(language=template_language, content=template_content)
            template_parameters = initial_template_parameters(
                lead_name=lead.full_name,
                project_name=project.name if project else None,
            )
            persisted_content = render_initial_template(template_content or "", template_parameters)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        message_metadata.update({
            "delivery_kind": "whatsapp_template",
            "template_name": template_name,
            "template_language": template_language,
            "template_parameters": {
                "lead_first_name": template_parameters[0],
                "project_name": template_parameters[1],
            },
            "rendered_content": persisted_content,
            "generated_draft": content,
        })
    if conversation.channel == "whatsapp" and not uses_whatsapp_template:
        if not _whatsapp_customer_window_open(db, conversation):
            raise HTTPException(
                status_code=422,
                detail="WhatsApp free-form messages require a customer reply in the previous 24 hours.",
            )
    if idempotency_key:
        existing_outbound = db.query(OutboundMessage).filter(
            OutboundMessage.idempotency_key == idempotency_key,
        ).first()
        if existing_outbound:
            existing_message = db.query(SalesMessage).filter(
                SalesMessage.conversation_id == conversation.id,
                SalesMessage.direction == "outbound",
                SalesMessage.content == existing_outbound.content,
            ).order_by(SalesMessage.created_at.desc()).first()
            if existing_outbound.status != "failed" and existing_message:
                return existing_message
            if existing_outbound.status == "failed" and existing_message:
                outbound = existing_outbound
                message = existing_message
                outbound.status = "queued"; outbound.last_error = None
                message.status = "queued"
            else:
                raise HTTPException(status_code=409, detail="The initial SMS request is already being processed.")
        else:
            outbound = None
            message = None
    else:
        outbound = None
        message = None
    outbound = outbound or OutboundMessage(
        conversation_id=conversation.id, agent_run_id=agent_run_id,
        idempotency_key=idempotency_key or f"{conversation.provider}:{conversation.id}:{uuid.uuid4()}", channel=conversation.channel,
        provider=conversation.provider,
        recipient=lead.phone, content=persisted_content, status="queued",
        approved_by_user_id=author_user_id,
        approved_at=datetime.utcnow() if author_user_id else None,
    )
    message = message or SalesMessage(
        conversation_id=conversation.id, channel=conversation.channel, direction="outbound", role=role,
        author_user_id=author_user_id, content=persisted_content, status="queued",
        metadata_json=message_metadata, created_at=datetime.utcnow(),
    )
    db.add_all([outbound, message]); db.commit()
    share_ids = [str(value) for value in message_metadata.get("sales_asset_share_ids", []) if value]
    if share_ids:
        shares = db.query(SalesAssetShare).filter(
            SalesAssetShare.id.in_(share_ids),
            SalesAssetShare.company_id == conversation.company_id,
            SalesAssetShare.lead_id == lead.id,
        ).all()
        for share in shares:
            share.outbound_message_id = outbound.id
            db.add(share)
        db.commit()
    try:
        if conversation.channel == "sms":
            result = await send_sms(
                db, provider=conversation.provider, company_id=conversation.company_id,
                to=lead.phone, body=content,
            )
        else:
            result = await send_message(
                db, provider=conversation.provider, channel=conversation.channel,
                company_id=conversation.company_id, to=lead.phone, body=content,
                use_initial_template=uses_whatsapp_template,
                template_parameters=template_parameters,
            )
    except Exception as exc:
        outbound.status = "failed"; outbound.last_error = type(exc).__name__
        message.status = "failed"
        for share in db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(share_ids)).all() if share_ids else []:
            asset_share_service.record_event(db, share=share, event_type="delivery_failed")
        db.commit()
        raise
    sid = result.get("sid")
    status = result.get("status") or "queued"
    outbound.provider_message_id = sid; outbound.status = status; outbound.sent_at = datetime.utcnow()
    message.provider_message_id = sid; message.status = status
    for share in db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(share_ids)).all() if share_ids else []:
        asset_share_service.record_event(db, share=share, event_type="message_dispatched")
    db.commit(); db.refresh(message)
    return message


def _asset_request_count(history: list[SalesMessage], inbound_text: str) -> int:
    return sum(
        "assets" in requested_topics(item.content)
        for item in history if item.direction == "inbound" or item.role == "user"
    )


def _select_asset_for_request(assets: list[dict], inbound_text: str) -> dict | None:
    if not assets:
        return None
    text = (inbound_text or "").casefold()
    preferred = (
        "floor_plan" if any(term in text for term in ("floor plan", "blueprint", "plan")) else
        "price_list" if "price" in text else
        "brochure" if any(term in text for term in ("brochure", "document", "pdf")) else None
    )
    if preferred == "floor_plan":
        capable = next((item for item in assets if "floor_plans" in (item.get("capabilities") or [])), None)
        if capable:
            return capable
    if "virtual tour" in text or "360" in text:
        capable = next((item for item in assets if "virtual_tour" in (item.get("capabilities") or [])), None)
        if capable:
            return capable
    return next((item for item in assets if item.get("asset_type") == preferred), assets[0])


def _denies_available_asset(reply: str | None) -> bool:
    """Detect a model refusal that contradicts the deterministic share action."""
    return bool(re.search(
        r"\b(?:cannot|can't|can not|unable to|not able to|do not have (?:the )?(?:ability|option) to)\b"
        r"[^.!?\n]{0,100}\b(?:share|send|provide|attach|access)\b",
        reply or "",
        re.IGNORECASE,
    ))


def _execute_share_actions(
    db: Session, *, conversation: SalesConversation, lead: Lead, run: AgentRun,
    reply: str | None, actions: list[dict], commercial: dict, inbound_text: str,
) -> tuple[str | None, list[dict], list[str]]:
    """Validate model proposals and mint links only at the dispatch boundary."""
    approved = {item["asset_id"]: item for item in commercial.get("available_assets", [])}
    requested = "assets" in requested_topics(inbound_text)
    pending = approved.get(conversation.pending_asset_id or "")
    consented = bool(pending and AFFIRMATIVE.match(inbound_text or ""))
    explicit_request = bool(requested and EXPLICIT_ASSET_SHARE.search(inbound_text or ""))
    if consented:
        actions = [
            action for action in actions
            if not isinstance(action, dict) or action.get("type") != "share_asset"
        ]
        actions.append({
            "type": "share_asset", "asset_id": pending["asset_id"],
            "reason": "lead_confirmed_material_offer",
        })
        conversation.pending_asset_id = None
        conversation.pending_asset_offered_at = None
        db.add(conversation)
        db.flush()
    elif requested and approved:
        selected = _select_asset_for_request(list(approved.values()), inbound_text)
        if selected:
            if explicit_request:
                actions = [
                    action for action in actions
                    if not isinstance(action, dict) or action.get("type") != "share_asset"
                ]
                actions.append({
                    "type": "share_asset", "asset_id": selected["asset_id"],
                    "reason": "lead_explicitly_requested_material",
                })
                consented = True
                conversation.pending_asset_id = None
                conversation.pending_asset_offered_at = None
                db.add(conversation)
                db.flush()
            else:
                conversation.pending_asset_id = selected["asset_id"]
                conversation.pending_asset_offered_at = datetime.utcnow()
                db.add(conversation)
                db.flush()
                actions = [
                    action for action in actions
                    if not isinstance(action, dict) or action.get("type") != "share_asset"
                ]
                capabilities = selected.get("capabilities") or []
                details = []
                if "floor_plans" in capabilities:
                    details.append("floor plans")
                if "virtual_tour" in capabilities:
                    details.append("a virtual tour")
                detail = f" It includes {' and '.join(details)}." if details else ""
                return (
                    f"I have an approved file called {selected.get('name') or 'Project material'}.{detail} "
                    "Would you like me to send the secure link here?",
                    actions,
                    [],
                )

    if not consented:
        actions = [
            action for action in actions
            if not isinstance(action, dict) or action.get("type") != "share_asset"
        ]

    links: list[str] = []
    share_ids: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "share_asset":
            continue
        asset_id = str(action.get("asset_id") or "")
        metadata = approved.get(asset_id)
        if not metadata or asset_id in seen:
            continue
        asset = db.query(ProjectSalesAsset).filter(
            ProjectSalesAsset.id == asset_id,
            ProjectSalesAsset.company_id == conversation.company_id,
            ProjectSalesAsset.project_id == conversation.project_id,
            ProjectSalesAsset.approval_status == "approved",
        ).first()
        if not asset:
            continue
        url, share = asset_share_service.issue(
            db,
            company_id=conversation.company_id,
            project_id=conversation.project_id,
            lead_id=lead.id,
            source_id=asset.source_id,
            sales_asset_id=asset.id,
            channel=conversation.channel,
            agent_run_id=run.id,
        )
        links.append(f"{asset.display_name}: {url}")
        share_ids.append(share.id)
        for embedded in metadata.get("links") or []:
            if len(links) >= 3:
                break
            if embedded.get("kind") not in {"virtual_tour", "location_map"}:
                continue
            external_url, external_share = asset_share_service.issue(
                db,
                company_id=conversation.company_id,
                project_id=conversation.project_id,
                lead_id=lead.id,
                source_id=asset.source_id,
                sales_asset_id=asset.id,
                channel=conversation.channel,
                agent_run_id=run.id,
                target_url=str(embedded.get("url") or ""),
            )
            links.append(f"{embedded.get('label') or 'Related resource'}: {external_url}")
            share_ids.append(external_share.id)
        seen.add(asset_id)
        if len(links) >= 3:
            break
    if links:
        cleaned = (reply or "").strip()
        if not cleaned or _denies_available_asset(cleaned):
            cleaned = "Here is the approved information you requested."
        reply = f"{cleaned}\n\n" + "\n".join(links)
    return reply, actions, share_ids


def _schedule_next_action(db: Session, conversation: SalesConversation, lead: Lead, event_id: str) -> None:
    if lead.is_opt_out or conversation.is_paused:
        return
    cadence = (get_ai_config(db, None).agent_ventas or {}).get("cadence_config", {})
    delays = {"hot": int(cadence.get("hot_hours", 24)), "warm": int(cadence.get("warm_hours", 72)), "cold": int(cadence.get("cold_hours", 24 * 14))}
    hours = delays.get(lead.intent_tier, 72)
    project = db.query(Project).filter(Project.id == conversation.project_id).first()
    scheduled_at = next_cadence_time(
        now=datetime.utcnow(), timezone_name=project.timezone if project else "UTC", delay_hours=hours,
    )
    scheduled_at = max(scheduled_at, next_allowed_proactive_time(
        db, company_id=conversation.company_id, project_id=conversation.project_id, now=scheduled_at,
    ))
    if not db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == conversation.id,
        SalesFollowUpJob.status == "pending",
    ).first():
        db.add(SalesFollowUpJob(
            conversation_id=conversation.id,
            idempotency_key=f"live-followup:{conversation.id}:{event_id}",
            scheduled_at=scheduled_at, reason=f"{lead.intent_tier}_cadence", attempt_number=1,
        ))
        lead.next_action_at = scheduled_at


async def start_live_lead(lead_id: str) -> None:
    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_demo.is_(False)).first()
        if not lead or not lead.project_id or lead.is_opt_out:
            return
        try:
            await launch_live_lead(db, lead)
        except HTTPException as exc:
            if exc.status_code == 409:
                lead.agent_status = "routing_blocked"
                db.commit()
                return
            raise
    finally:
        db.close()


def prepare_meta_simulation(db: Session, lead: Lead) -> tuple[SalesConversation, SalesMessage]:
    """Open an interactive in-app conversation when live SMS is unavailable.

    The lead remains a real, auditable Meta lead. Only message delivery is
    simulated, so the existing simulation endpoint can exercise the same AI
    protocol without pretending that an SMS was sent.
    """
    project = db.query(Project).filter(
        Project.id == lead.project_id,
        Project.company_id == lead.company_id,
    ).one()
    campaign = (
        db.query(ProjectCampaign).filter(ProjectCampaign.id == lead.campaign_id).first()
        if lead.campaign_id else None
    )
    conversation = get_or_create_conversation(db, lead, channel="simulation")
    conversation.is_paused = False
    conversation.pause_reason = None
    conversation.automation_level = 0
    existing = db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation.id,
        SalesMessage.metadata_json["event_kind"].as_string() == "meta_lead_simulation_started",
    ).first()
    if existing:
        return conversation, existing
    message = SalesMessage(
        conversation_id=conversation.id,
        channel="simulation",
        direction="outbound",
        role="assistant",
        content=_initial_message(lead, project, campaign),
        status="simulated",
        metadata_json={
            "event_kind": "meta_lead_simulation_started",
            "delivery": "not_sent",
            "reason": "sms_provider_disabled",
            "lead_id": lead.id,
            "project_id": project.id,
        },
        created_at=datetime.utcnow(),
    )
    lead.agent_status = "simulation"
    lead.funnel_stage = FunnelStage.CONTACTED
    lead.pipeline_stage = "S01_RESEARCH"
    lead.last_interaction_at = datetime.utcnow()
    conversation.stage = "contacted"
    conversation.updated_at = datetime.utcnow()
    db.add_all([lead, conversation, message])
    db.commit()
    db.refresh(message)
    return conversation, message


async def launch_live_lead(db: Session, lead: Lead) -> tuple[SalesConversation | None, SalesMessage | None]:
    """Start or safely re-contextualize the one physical SMS thread for this sender/recipient."""
    channel = company_live_channel(db, company_id=lead.company_id, requested=lead.preferred_channel)
    provider = "telnyx" if channel == "whatsapp" else live_provider(db, company_id=lead.company_id)
    if not provider or not channel:
        return prepare_meta_simulation(db, lead)
    lead.preferred_channel = channel
    project = db.query(Project).filter(Project.id == lead.project_id, Project.company_id == lead.company_id).one()
    campaign = db.query(ProjectCampaign).filter(ProjectCampaign.id == lead.campaign_id).first() if lead.campaign_id else None
    ensure_contact(db, lead)
    conversation, should_send = get_or_create_live_conversation(db, lead, provider=provider)
    prior_message_count = scoped_messages_query(db, conversation, lead_id=lead.id).filter(
        SalesMessage.status != "failed",
    ).count()
    if not should_send and prior_message_count:
        return conversation, None
    allowed_at = next_allowed_proactive_time(
        db, company_id=lead.company_id, project_id=lead.project_id, now=datetime.utcnow(),
    )
    if allowed_at > datetime.utcnow():
        if not db.query(SalesFollowUpJob).filter(
            SalesFollowUpJob.conversation_id == conversation.id,
            SalesFollowUpJob.status == "pending",
        ).first():
            db.add(SalesFollowUpJob(
                conversation_id=conversation.id, idempotency_key=f"operating-window-initial:{lead.id}",
                scheduled_at=allowed_at, status="pending", reason="operating_window_initial", attempt_number=1,
            ))
        lead.next_action_at = allowed_at; lead.agent_status = "scheduled"
        db.commit()
        return conversation, None
    content = _initial_message(lead, project, campaign)
    event_kind = "meta_lead_first_contact" if lead.platform.startswith("meta") else "manual_lead_first_contact"
    if prior_message_count:
        first_name = (lead.full_name or "there").split()[0]
        content = (
            f"Hi {first_name}, I also received your interest in {campaign.name if campaign else project.name}. "
            f"I'll continue here so your conversation stays in one place. What would you like to know about {project.name}?"
        )
        event_kind = "meta_lead_project_context_changed"
    message = await _dispatch(
        db, conversation=conversation, lead=lead, content=content, role="assistant", agent_run_id=None,
        metadata={"event_kind": event_kind, "lead_id": lead.id, "project_id": project.id},
        idempotency_key=f"live-initial:{lead.id}",
    )
    lead.agent_status = "active"; lead.funnel_stage = FunnelStage.CONTACTED
    lead.pipeline_stage = "S01_RESEARCH"; lead.last_interaction_at = datetime.utcnow()
    _schedule_next_action(db, conversation, lead, f"initial:{lead.id}")
    db.commit()
    return conversation, message


def _prepare_run(
    db: Session, *, conversation: SalesConversation, event_id: str,
    message_id: str, model: str = "pending",
) -> AgentRun | None:
    existing = db.query(AgentRun).filter(AgentRun.event_id == event_id).first()
    if existing and existing.status in {"completed", "blocked"}:
        return None
    run = existing or AgentRun(
        conversation_id=conversation.id, event_id=event_id, mode="live",
        graph_version=GRAPH_VERSION, toolset_version=TOOLSET_VERSION,
        prompt_snapshot={}, model=model, input_snapshot={"message_id": message_id},
    )
    run.status = "running"
    run.error_code = None
    run.completed_at = None
    if existing:
        run.model = model
        run.input_snapshot = {"message_id": message_id, "retry": True}
    db.add(run); db.commit(); db.refresh(run)
    return run


def _lead_intelligence_input(history: list[SalesMessage]) -> tuple[str, int]:
    """Return lead-authored evidence only; agent copy must never inflate intent."""
    lead_messages = [
        item for item in history
        if item.direction == "inbound" or item.role == "user"
    ]
    return " ".join(item.content for item in lead_messages[-20:]), len(lead_messages)


async def _process_deterministic_appointment_turn(
    db: Session, *, conversation: SalesConversation, lead: Lead,
    project: Project, inbound: SalesMessage, event_id: str,
) -> bool:
    """Own every appointment turn before the LLM so provider/model failures cannot block scheduling."""
    now = datetime.utcnow()
    selected = _offered_slot_selection(
        db, conversation_id=conversation.id, inbound_text=inbound.content,
        project=project, now=now,
    )
    awaiting_location = bool((lead.meta_form_data or {}).get("pending_location_request"))
    scheduling_request = _is_availability_request(
        inbound.content, now=now, zone=_project_zone(project),
        appointment_context=_recent_appointment_context(db, conversation.id),
    )
    if not (selected or awaiting_location or scheduling_request):
        return False

    run = _prepare_run(
        db, conversation=conversation, event_id=event_id,
        message_id=inbound.id, model="deterministic/appointment-routing",
    )
    if run is None:
        return True

    location_ready, location_question, location_resume = _confirm_or_request_location(
        project, lead, inbound.content,
    )
    offered_slots: list[datetime] = []
    if not location_ready:
        reply = location_question
        actions = [{"type": "request_visit_location"}]
    elif selected:
        try:
            meeting, user = create_agent_appointment(
                db, lead=lead, starts_at=selected, duration_minutes=45, modality="showroom",
            )
            reply = _appointment_confirmation(
                project=project, lead=lead, user=user, starts_at=meeting.meeting_time,
            )
            conversation.stage = "appointment_confirmed"
            conversation.is_paused = True
            conversation.pause_reason = "Appointment confirmed"
            lead.pipeline_stage = "S09_HANDOFF"
            lead.agent_status = "appointment_confirmed"
            lead.next_action_at = None
            actions = [{"type": "appointment_confirmed", "meeting_id": meeting.id}]
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            reply, offered_slots = _availability_reply(
                db, project=project, inbound_text=location_resume or inbound.content, now=now,
            )
            actions = [{"type": "request_available_slots"}]
            if offered_slots:
                actions.append({"type": "offer_appointment"})
    else:
        reply, offered_slots = _availability_reply(
            db, project=project, inbound_text=location_resume or inbound.content, now=now,
        )
        actions = [{"type": "request_available_slots"}]
        if offered_slots:
            actions.append({"type": "offer_appointment"})

    history = scoped_messages_query(
        db, conversation, lead_id=lead.id,
    ).order_by(SalesMessage.created_at).all()
    lead_history, lead_message_count = _lead_intelligence_input(history)
    update_lead_intelligence(
        db, lead, inbound_text=inbound.content,
        conversation_text=lead_history,
        message_count=lead_message_count,
    )
    if lead.agent_status != "appointment_confirmed":
        lead.pipeline_stage = "S08_APPOINTMENT"
    run.output_snapshot = {
        "reply": reply, "proposed_actions": actions,
        "requires_human": False, "policy_violations": [], "error_code": None,
    }
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    conversation.updated_at = datetime.utcnow()
    lead.last_interaction_at = datetime.utcnow()
    db.add_all([run, conversation, lead]); db.commit()
    await _dispatch(
        db, conversation=conversation, lead=lead, content=reply,
        role="assistant", agent_run_id=run.id,
        metadata={
            "event_kind": "deterministic_appointment_routing",
            "appointment_offer": {
                "slots": [slot.isoformat() for slot in offered_slots],
                "duration_minutes": 45,
                "project_timezone": project.timezone or "UTC",
            },
        },
        idempotency_key=f"appointment-turn:{event_id}",
    )
    if lead.agent_status != "appointment_confirmed":
        _schedule_next_action(db, conversation, lead, event_id)
    db.commit()
    return True


async def process_live_inbound(conversation_id: str, inbound_message_id: str) -> None:
    db = SessionLocal()
    try:
        conversation = db.query(SalesConversation).filter(SalesConversation.id == conversation_id).with_for_update().first()
        inbound = db.query(SalesMessage).filter(SalesMessage.id == inbound_message_id).first()
        if not conversation or not inbound or conversation.is_paused:
            return
        lead = db.query(Lead).filter(Lead.id == conversation.lead_id, Lead.company_id == conversation.company_id).one()
        project = db.query(Project).filter(Project.id == conversation.project_id, Project.company_id == conversation.company_id).one()
        if lead.is_opt_out:
            return
        if inbound.content.strip().upper() in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
            lead.is_opt_out = True; lead.consent_status = "opted_out"; lead.agent_status = "paused"
            conversation.is_paused = True; conversation.pause_reason = "Lead opted out"
            db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id == conversation.id, SalesFollowUpJob.status == "pending").update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
            db.commit()
            await _dispatch(db, conversation=conversation, lead=lead, content="You have been unsubscribed and will not receive further messages.", role="assistant", agent_run_id=None, metadata={"event_kind": "opt_out"})
            return
        mandatory_reason = escalation_reason(inbound.content)
        if mandatory_reason:
            intervention_actions = [{
                "type": "request_callback" if mandatory_reason == "HUMAN_REQUESTED" else "request_human_review",
            }]
            create_intervention_case(
                db, conversation=conversation, lead=lead, reason=mandatory_reason,
                evidence=inbound.content,
            )
            db.commit()
            await _dispatch(
                db, conversation=conversation, lead=lead,
                content=_confirmed_handoff_reply(inbound.content, intervention_actions),
                role="assistant", agent_run_id=None,
                metadata={
                    "event_kind": "human_intervention",
                    "reason": mandatory_reason,
                    "proposed_actions": intervention_actions,
                },
                idempotency_key=f"human-intervention:{conversation.id}:{inbound.id}",
            )
            return
        event_id = f"{conversation.provider}:{inbound.provider_message_id or inbound.id}"
        if await _process_deterministic_appointment_turn(
            db, conversation=conversation, lead=lead, project=project,
            inbound=inbound, event_id=event_id,
        ):
            return
        run = _prepare_run(
            db, conversation=conversation, event_id=event_id, message_id=inbound.id,
        )
        if run is None:
            return
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id, "mode": "live", "conversation_id": conversation.id,
            "company_id": lead.company_id, "project_id": project.id, "campaign_id": lead.campaign_id,
            "lead_id": lead.id, "channel": conversation.channel, "inbound_text": inbound.content,
            "event_kind": "lead_message", "requires_human": False, "policy_violations": [],
        })
        reply = result.get("proposed_reply")
        actions = result.get("proposed_actions", [])
        if result.get("error_code") == "invalid_model_contract":
            raise RuntimeError("The Sales Agent returned an invalid response contract.")
        if not result.get("policy_violations"):
            merge_extracted_facts(
                lead, result.get("extracted_facts"), evidence=inbound.content,
            )
        history = scoped_messages_query(
            db, conversation, lead_id=lead.id,
        ).order_by(SalesMessage.created_at).all()
        commercial = result.get("commercial_context") or {}
        available_assets = commercial.get("available_assets") or []
        if "assets" in requested_topics(inbound.content):
            if available_assets and not result.get("policy_violations"):
                # A verified material request is executable; model uncertainty
                # must not incorrectly force a handoff.
                result["requires_human"] = False
            elif not available_assets and _asset_request_count(history, inbound.content) >= 2:
                result["requires_human"] = True
                actions = [*actions, {"type": "request_human_review", "reason": "approved_material_unavailable"}]
        if result.get("requires_human"):
            create_intervention_case(
                db, conversation=conversation, lead=lead,
                reason="LOW_CONFIDENCE" if not result.get("policy_violations") else "POLICY_VIOLATION",
                evidence=inbound.content,
            )
            reply = _confirmed_handoff_reply(inbound.content, actions)
        share_ids: list[str] = []
        if not result.get("requires_human"):
            reply, actions, share_ids = _execute_share_actions(
                db, conversation=conversation, lead=lead, run=run,
                reply=reply, actions=actions, commercial=commercial,
                inbound_text=inbound.content,
            )
        lead_history, lead_message_count = _lead_intelligence_input(history)
        update_lead_intelligence(
            db, lead, inbound_text=inbound.content,
            conversation_text=lead_history, message_count=lead_message_count,
        )
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {
            "reply": reply, "proposed_actions": actions,
            "extracted_facts": result.get("extracted_facts", []),
            "requires_human": result.get("requires_human", False),
            "policy_violations": result.get("policy_violations", []),
            "error_code": result.get("error_code"),
        }
        run.status = "blocked" if result.get("requires_human") else "completed"; run.completed_at = datetime.utcnow()
        conversation.updated_at = datetime.utcnow(); lead.last_interaction_at = datetime.utcnow()
        db.add_all([run, conversation, lead]); db.commit()
        # The LLM call runs without holding a database lock. Re-lock immediately
        # before dispatch so an administrator taking manual control wins the race.
        db.expire(conversation)
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == conversation.id,
        ).populate_existing().with_for_update().one()
        if reply and (
            not conversation.is_paused
            or conversation.pause_reason == "Appointment confirmed"
            or (conversation.pause_reason or "").startswith("Human intervention")
        ):
            await _dispatch(
                db, conversation=conversation, lead=lead, content=reply,
                role="assistant", agent_run_id=run.id,
                metadata={
                    "event_kind": "agent_reply", "proposed_actions": actions,
                    "sales_asset_share_ids": share_ids,
                },
            )
        _schedule_next_action(db, conversation, lead, event_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        event_id = None
        inbound = db.query(SalesMessage).filter(SalesMessage.id == inbound_message_id).first()
        conversation = db.query(SalesConversation).filter(SalesConversation.id == conversation_id).first()
        if inbound and conversation:
            event_id = f"{conversation.provider}:{inbound.provider_message_id or inbound.id}"
        run = db.query(AgentRun).filter(AgentRun.event_id == event_id).first() if event_id else None
        if run:
            run.status = "failed"
            run.error_code = type(exc).__name__[:80]
            run.output_snapshot = {**(run.output_snapshot or {}), "safe_error": "Agent turn processing failed."}
            run.completed_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()


async def process_live_inbound_job(job_id: str) -> None:
    """Process one durable inbound turn and expose bounded retry state to operators."""
    db = SessionLocal()
    try:
        job = db.query(SalesInboundJob).filter(SalesInboundJob.id == job_id).first()
        if not job or job.status != "processing":
            return
        message = db.query(SalesMessage).filter(SalesMessage.id == job.message_id).one()
        message.metadata_json = {**(message.metadata_json or {}), "agent_turn_status": "processing"}
        db.commit()
        await process_live_inbound(job.conversation_id, job.message_id)
        db.expire_all()
        job = db.query(SalesInboundJob).filter(SalesInboundJob.id == job_id).one()
        message = db.query(SalesMessage).filter(SalesMessage.id == job.message_id).one()
        job.status = "processed"
        job.processed_at = datetime.utcnow()
        job.error_code = None
        job.error_message = None
        message.metadata_json = {
            **(message.metadata_json or {}),
            "agent_turn_status": "processed",
            "agent_turn_error": None,
        }
        webhook_event_id = (message.metadata_json or {}).get("webhook_event_id")
        if webhook_event_id:
            event = db.query(ExternalWebhookEvent).filter(
                ExternalWebhookEvent.platform == (message.metadata_json or {}).get("provider"),
                ExternalWebhookEvent.external_event_id == webhook_event_id,
            ).first()
            if event:
                event.status = "processed"
                event.processed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.query(SalesInboundJob).filter(SalesInboundJob.id == job_id).first()
        if job:
            terminal = (job.attempt_number or 0) >= 3
            job.status = "failed" if terminal else "retry"
            job.claimed_at = None
            job.scheduled_at = datetime.utcnow() + timedelta(minutes=5 if (job.attempt_number or 0) > 1 else 1)
            job.error_code = type(exc).__name__[:80]
            job.error_message = "Agent turn processing failed. Retry is available."
            message = db.query(SalesMessage).filter(SalesMessage.id == job.message_id).first()
            if message:
                message.metadata_json = {
                    **(message.metadata_json or {}),
                    "agent_turn_status": job.status,
                    "agent_turn_error": job.error_message,
                }
            if terminal:
                conversation = db.query(SalesConversation).filter(
                    SalesConversation.id == job.conversation_id,
                ).first()
                lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first() if conversation else None
                if lead:
                    lead.agent_status = "attention_required"
            db.commit()
        raise
    finally:
        db.close()


def retry_failed_inbound_turn(
    db: Session, *, company_id: str, conversation_id: str,
) -> SalesInboundJob:
    conversation = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    job = db.query(SalesInboundJob).filter(
        SalesInboundJob.conversation_id == conversation_id,
        SalesInboundJob.status == "failed",
    ).order_by(SalesInboundJob.created_at.desc()).first()
    if not job:
        raise HTTPException(status_code=409, detail="This conversation has no failed agent turn to retry.")
    job.status = "retry"
    job.attempt_number = 0
    job.scheduled_at = datetime.utcnow()
    job.claimed_at = None
    job.processed_at = None
    job.error_code = None
    job.error_message = None
    message = db.query(SalesMessage).filter(SalesMessage.id == job.message_id).first()
    if message:
        message.metadata_json = {
            **(message.metadata_json or {}),
            "agent_turn_status": "retry",
            "agent_turn_error": None,
        }
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
    if lead and not conversation.is_paused:
        lead.agent_status = "active"
    db.commit()
    return job


async def send_manual_message(db: Session, *, conversation_id: str, company_id: str, user_id: str, content: str) -> SalesMessage:
    conversation = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    ).with_for_update().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.channel not in {"sms", "whatsapp"}:
        raise HTTPException(status_code=409, detail="Manual provider messages are available only for live messaging conversations.")
    if not conversation.is_paused:
        label = "WhatsApp message" if conversation.channel == "whatsapp" else "SMS"
        raise HTTPException(status_code=409, detail=f"Pause the AI before sending a manual {label}.")
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id, Lead.company_id == company_id).one()
    if lead.is_opt_out:
        raise HTTPException(status_code=409, detail="This lead opted out of messaging.")
    policy = operating_policy_for(
        db, company_id=conversation.company_id, project_id=conversation.project_id,
    )
    if policy and policy.is_enabled and policy.enforce_manual_messages:
        now = datetime.utcnow()
        allowed_at = next_allowed_proactive_time(
            db, company_id=conversation.company_id, project_id=conversation.project_id, now=now,
        )
        if allowed_at > now:
            raise HTTPException(status_code=409, detail={
                "code": "OUTSIDE_OPERATING_WINDOW",
                "message": "This manual message is outside the configured contact window.",
                "next_allowed_at": allowed_at.isoformat(),
            })
    message = await _dispatch(
        db, conversation=conversation, lead=lead, content=content,
        role="human", agent_run_id=None, author_user_id=user_id,
        metadata={"event_kind": f"manual_{conversation.channel}"},
    )
    conversation.pause_reason = "Manual control active"
    conversation.updated_at = datetime.utcnow(); db.commit()
    return message


async def process_live_followup_job(job_id: str) -> None:
    """Generate one durable cadence message; safe to retry without duplicate SMS."""
    db = SessionLocal()
    try:
        job = db.query(SalesFollowUpJob).filter(SalesFollowUpJob.id == job_id).first()
        if not job or job.status != "processing":
            return
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == job.conversation_id,
        ).with_for_update().one()
        lead = db.query(Lead).filter(
            Lead.id == conversation.lead_id,
            Lead.company_id == conversation.company_id,
        ).one()
        if conversation.channel not in {"sms", "whatsapp"} or conversation.is_paused or lead.is_opt_out:
            job.status = "cancelled"; job.processed_at = datetime.utcnow(); db.commit(); return
        if conversation.channel == "whatsapp" and not _whatsapp_customer_window_open(db, conversation):
            # Re-engagement outside the customer-service window requires a
            # separately approved template; never attempt an illegal free-form send.
            job.status = "cancelled"; job.processed_at = datetime.utcnow(); db.commit(); return
        dispatch_key = f"{conversation.provider}-followup:{job.id}"
        if db.query(OutboundMessage).filter(OutboundMessage.idempotency_key == dispatch_key).first():
            job.status = "processed"; job.processed_at = datetime.utcnow(); db.commit(); return
        project = db.query(Project).filter(
            Project.id == conversation.project_id,
            Project.company_id == conversation.company_id,
        ).one()
        allowed_at = next_allowed_proactive_time(
            db, company_id=conversation.company_id, project_id=conversation.project_id, now=datetime.utcnow(),
        )
        if allowed_at > datetime.utcnow():
            job.status = "pending"; job.scheduled_at = allowed_at; db.commit(); return
        event_id = f"followup:{job.id}"
        run = AgentRun(
            conversation_id=conversation.id, event_id=event_id, mode="live", status="running",
            graph_version=GRAPH_VERSION, toolset_version=TOOLSET_VERSION,
            prompt_snapshot={}, model="pending", input_snapshot={"follow_up_job_id": job.id},
        )
        db.add(run); db.commit(); db.refresh(run)
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id, "mode": "live", "conversation_id": conversation.id,
            "company_id": lead.company_id, "project_id": project.id,
            "campaign_id": lead.campaign_id, "lead_id": lead.id, "channel": conversation.channel,
            "inbound_text": (
                "Write the next concise, helpful SMS follow-up based only on the verified context and chat. "
                "Do not invent urgency, inventory, price or availability. Include a simple question and opt-out language."
            ),
            "event_kind": "scheduled_follow_up", "requires_human": False, "policy_violations": [],
        })
        reply = result.get("proposed_reply")
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {"reply": reply, "proposed_actions": result.get("proposed_actions", [])}
        if result.get("requires_human"):
            create_intervention_case(
                db, conversation=conversation, lead=lead,
                reason="LOW_CONFIDENCE" if not result.get("policy_violations") else "POLICY_VIOLATION",
                evidence="Scheduled follow-up generation required human review.",
            )
        run.status = "completed" if reply and not result.get("requires_human") else (
            "blocked" if result.get("requires_human") else "failed"
        )
        run.error_code = result.get("error_code")
        run.completed_at = datetime.utcnow()
        db.add(run); db.commit()
        db.expire(conversation)
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == conversation.id,
        ).populate_existing().with_for_update().one()
        if not reply or result.get("requires_human") or conversation.is_paused or lead.is_opt_out:
            job.status = "cancelled" if conversation.is_paused or lead.is_opt_out else "failed"
            job.processed_at = datetime.utcnow(); db.commit(); return
        await _dispatch(
            db, conversation=conversation, lead=lead, content=reply, role="assistant",
            agent_run_id=run.id, metadata={"event_kind": "scheduled_follow_up", "reason": job.reason},
            idempotency_key=dispatch_key,
        )
        job.status = "processed"; job.processed_at = datetime.utcnow()
        lead.last_interaction_at = datetime.utcnow()
        if lead.pipeline_stage not in {"S07_OBJECTION", "S08_APPOINTMENT", "S09_HANDOFF"}:
            lead.pipeline_stage = "S06_NURTURE"
        _schedule_next_action(db, conversation, lead, event_id)
        db.add_all([job, lead]); db.commit()
    except Exception:
        db.rollback()
        job = db.query(SalesFollowUpJob).filter(SalesFollowUpJob.id == job_id).first()
        if job:
            job.status = "failed" if job.attempt_number >= 3 else "pending"
            job.attempt_number += 1
            job.scheduled_at = datetime.utcnow() + timedelta(minutes=5)
            db.commit()
        raise
    finally:
        db.close()
