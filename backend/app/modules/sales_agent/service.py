from __future__ import annotations

from datetime import datetime, timedelta
import uuid

from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import FunnelStage, Lead, Meeting

from .graph import GRAPH_VERSION, TOOLSET_VERSION, build_sales_graph
from .models import AgentRun, OutboundMessage, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage


def conversation_summaries(
    db: Session,
    *,
    company_id: str,
    project_id: str | None = None,
    sales_user_id: str | None = None,
) -> list[dict]:
    query = db.query(SalesConversation, Lead, Project).join(
        Lead, Lead.id == SalesConversation.lead_id,
    ).join(Project, Project.id == SalesConversation.project_id).filter(
        SalesConversation.company_id == company_id,
    )
    if project_id:
        query = query.filter(SalesConversation.project_id == project_id)
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    rows = query.order_by(SalesConversation.updated_at.desc()).all()
    result = []
    for conversation, lead, project in rows:
        last = db.query(SalesMessage).filter(
            SalesMessage.conversation_id == conversation.id,
        ).order_by(SalesMessage.created_at.desc()).first()
        simulation = db.query(SalesAgentSimulation).filter(
            SalesAgentSimulation.conversation_id == conversation.id,
        ).first()
        campaign = db.query(ProjectCampaign).filter(ProjectCampaign.id == conversation.campaign_id).first() if conversation.campaign_id else None
        meeting = db.query(Meeting).filter(Meeting.lead_id == lead.id).order_by(Meeting.created_at.desc()).first()
        result.append({
            "id": conversation.id, "lead_id": lead.id, "project_id": project.id,
            "campaign_id": conversation.campaign_id, "channel": conversation.channel,
            "stage": conversation.stage, "automation_level": conversation.automation_level,
            "is_paused": conversation.is_paused, "updated_at": conversation.updated_at,
            "lead_name": lead.full_name, "phone": lead.phone,
            "funnel_stage": lead.funnel_stage.value if hasattr(lead.funnel_stage, "value") else str(lead.funnel_stage),
            "intent_score": float(lead.intent_score or 0),
            "last_message": last.content if last else None,
            "last_message_at": last.created_at if last else None,
            "next_action_at": lead.next_action_at, "agent_status": lead.agent_status,
            "project_name": project.name, "is_demo": bool(project.is_demo),
            "campaign_name": campaign.name if campaign else None,
            "simulation_id": simulation.id if simulation else None,
            "simulation_status": simulation.status if simulation else None,
            "approval_status": simulation.approval_status if simulation else None,
            "virtual_now": simulation.virtual_now if simulation else None,
            "appointment_id": meeting.id if meeting else None,
            "assigned_sales_user_id": lead.assigned_sales_user_id,
        })
    return result


def conversation_messages(
    db: Session, *, company_id: str, conversation_id: str, sales_user_id: str | None = None,
) -> list[SalesMessage]:
    query = db.query(SalesConversation).join(Lead, Lead.id == SalesConversation.lead_id).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    conversation = query.first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    # A lead message and its generated answer can share virtual time. Direction
    # preserves the causal order before the stable id tie-breaker.
    return db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation.id,
    ).order_by(
        SalesMessage.created_at.asc(),
        case((SalesMessage.direction == "inbound", 0), else_=1),
        SalesMessage.id.asc(),
    ).all()


def set_conversation_action(
    db: Session, *, company_id: str, conversation_id: str, action: str,
    sales_user_id: str | None = None,
) -> SalesConversation:
    query = db.query(SalesConversation).join(Lead, Lead.id == SalesConversation.lead_id).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    conversation = query.first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if action == "resume":
        conversation.is_paused = False
        conversation.pause_reason = None
    else:
        conversation.is_paused = True
        conversation.pause_reason = "Human handoff requested" if action == "human_handoff" else "Paused by user"
    conversation.updated_at = datetime.utcnow()
    db.add(conversation); db.commit(); db.refresh(conversation)
    return conversation


def get_or_create_conversation(db: Session, lead: Lead, *, channel: str) -> SalesConversation:
    conversation = db.query(SalesConversation).filter(
        SalesConversation.lead_id == lead.id,
        SalesConversation.channel == channel,
    ).first()
    if conversation:
        return conversation
    conversation = SalesConversation(
        company_id=lead.company_id,
        project_id=lead.project_id,
        campaign_id=lead.campaign_id,
        lead_id=lead.id,
        channel=channel,
        automation_level=0,
        is_paused=True,
        pause_reason="Simulation/draft mode",
    )
    db.add(conversation)
    db.flush()
    return conversation


async def simulate_turn(
    db: Session,
    *,
    company_id: str,
    lead_id: str,
    inbound_text: str,
    event_id: str | None = None,
    record_inbound: bool = True,
    event_kind: str = "lead_message",
    follow_up_hours: int | None = None,
    virtual_now: datetime | None = None,
    sales_user_id: str | None = None,
) -> dict:
    lead_query = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id)
    if sales_user_id:
        lead_query = lead_query.filter(Lead.assigned_sales_user_id == sales_user_id)
    lead = lead_query.first()
    if not lead or not lead.project_id:
        raise HTTPException(status_code=404, detail="Lead not found or not associated with a Project.")
    project = db.query(Project).filter(Project.id == lead.project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not lead.is_demo:
        raise HTTPException(status_code=409, detail="This endpoint accepts simulation leads only.")
    event_id = event_id or f"simulation:{uuid.uuid4()}"
    existing = db.query(AgentRun).filter(AgentRun.event_id == event_id).first()
    if existing:
        output = existing.output_snapshot or {}
        return _response(existing, output)

    conversation = get_or_create_conversation(db, lead, channel="simulation")
    now = virtual_now or datetime.utcnow()
    conversation.is_paused = False
    conversation.pause_reason = None
    conversation.updated_at = now
    lead.last_interaction_at = now
    if lead.funnel_stage == FunnelStage.NEW:
        lead.funnel_stage = FunnelStage.CONTACTED
        lead.stage_changed_at = now
    if record_inbound:
        db.add(SalesMessage(
            conversation_id=conversation.id,
            channel="simulation",
            direction="inbound",
            role="user",
            content=inbound_text,
            status="received",
            created_at=now,
        ))
    normalized = inbound_text.strip().upper()
    if record_inbound and normalized in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
        lead.is_opt_out = True
        lead.consent_status = "opted_out"
        lead.agent_status = "paused"
        lead.next_action_at = None
        conversation.is_paused = True
        conversation.pause_reason = "Lead opted out"
        db.query(SalesFollowUpJob).filter(
            SalesFollowUpJob.conversation_id == conversation.id,
            SalesFollowUpJob.status == "pending",
        ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
        db.add(SalesMessage(
            conversation_id=conversation.id,
            channel="simulation",
            direction="outbound",
            role="assistant",
            content="You have been unsubscribed and will not receive further messages.",
            status="simulated",
            created_at=now,
        ))
        db.commit()
        return {
            "run_id": f"optout:{conversation.id}", "conversation_id": conversation.id,
            "status": "completed", "mode": "simulation",
            "reply": "You have been unsubscribed and will not receive further messages.",
            "intent": "opt_out", "proposed_actions": [], "requires_human": False,
            "policy_violations": [], "draft_id": None,
        }
    run = AgentRun(
        conversation_id=conversation.id,
        event_id=event_id,
        mode="simulation",
        status="running",
        graph_version=GRAPH_VERSION,
        toolset_version=TOOLSET_VERSION,
        prompt_snapshot={},
        model="pending",
        input_snapshot={"lead_id": lead.id, "message": inbound_text, "event_kind": event_kind},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id,
            "mode": "simulation",
            "conversation_id": conversation.id,
            "company_id": company_id,
            "project_id": project.id,
            "campaign_id": lead.campaign_id,
            "lead_id": lead.id,
            "channel": "simulation",
            "inbound_text": inbound_text,
            "event_kind": event_kind,
            "requires_human": False,
            "policy_violations": [],
        })
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {
            "reply": result.get("proposed_reply"),
            "intent": result.get("intent"),
            "proposed_actions": result.get("proposed_actions", []),
            "requires_human": result.get("requires_human", False),
            "policy_violations": result.get("policy_violations", []),
            "error_code": result.get("error_code"),
        }
        run.status = "blocked" if result.get("policy_violations") else "completed"
        run.error_code = result.get("error_code")
        run.completed_at = datetime.utcnow()
        draft = None
        if result.get("proposed_reply") and not result.get("policy_violations"):
            draft = OutboundMessage(
                conversation_id=conversation.id,
                agent_run_id=run.id,
                idempotency_key=f"outbound:{conversation.id}:{event_id}",
                channel="simulation",
                recipient=lead.channel_address or lead.phone,
                content=result["proposed_reply"],
                status="draft",
            )
            db.add(draft)
            db.add(SalesMessage(
                conversation_id=conversation.id,
                channel="simulation",
                direction="outbound",
                role="assistant",
                content=result["proposed_reply"],
                status=f"simulated_follow_up_{follow_up_hours or 24}h" if event_kind == "follow_up" else "simulated",
                metadata_json={"event_kind": event_kind, "follow_up_hours": follow_up_hours},
                created_at=now + timedelta(microseconds=1) if record_inbound else now,
            ))
            conversation.updated_at = now
            lead.agent_status = "simulation"
            pending_count = db.query(SalesFollowUpJob).filter(
                SalesFollowUpJob.conversation_id == conversation.id,
                SalesFollowUpJob.status == "pending",
            ).count()
            if pending_count == 0 and not lead.is_opt_out:
                attempt = 1 if event_kind != "follow_up" else min(3, 1 + db.query(SalesFollowUpJob).filter(
                    SalesFollowUpJob.conversation_id == conversation.id,
                    SalesFollowUpJob.status == "processed",
                ).count())
                if attempt <= 3:
                    scheduled_at = now + timedelta(hours=24 if attempt == 1 else 48)
                    db.add(SalesFollowUpJob(
                        conversation_id=conversation.id,
                        idempotency_key=f"followup:{conversation.id}:{event_id}",
                        scheduled_at=scheduled_at,
                        reason="no_response",
                        attempt_number=attempt,
                    ))
                    lead.next_action_at = scheduled_at
            db.add_all([conversation, lead])
        db.commit()
        db.refresh(run)
        response = _response(run, run.output_snapshot)
        response["draft_id"] = draft.id if draft else None
        return response
    except Exception as exc:
        db.rollback()
        run = db.query(AgentRun).filter(AgentRun.id == run.id).one()
        run.status = "failed"
        run.error_code = type(exc).__name__
        run.completed_at = datetime.utcnow()
        db.commit()
        raise


def _response(run: AgentRun, output: dict) -> dict:
    draft = None
    if run.id:
        # The caller may fill this without triggering an extra query.
        draft = None
    return {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "status": run.status,
        "mode": run.mode,
        "reply": output.get("reply"),
        "intent": output.get("intent"),
        "proposed_actions": output.get("proposed_actions", []),
        "requires_human": bool(output.get("requires_human")),
        "policy_violations": output.get("policy_violations", []),
        "draft_id": draft,
    }
