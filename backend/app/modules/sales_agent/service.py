from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead

from .graph import GRAPH_VERSION, TOOLSET_VERSION, build_sales_graph
from .models import AgentRun, OutboundMessage, SalesConversation, SalesMessage


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
) -> dict:
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
    if not lead or not lead.project_id:
        raise HTTPException(status_code=404, detail="Lead not found or not associated with a Project.")
    project = db.query(Project).filter(Project.id == lead.project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    event_id = event_id or f"simulation:{uuid.uuid4()}"
    existing = db.query(AgentRun).filter(AgentRun.event_id == event_id).first()
    if existing:
        output = existing.output_snapshot or {}
        return _response(existing, output)

    conversation = get_or_create_conversation(db, lead, channel="simulation")
    inbound = SalesMessage(
        conversation_id=conversation.id,
        channel="simulation",
        direction="inbound",
        role="user",
        content=inbound_text,
        status="received",
    )
    db.add(inbound)
    run = AgentRun(
        conversation_id=conversation.id,
        event_id=event_id,
        mode="simulation",
        status="running",
        graph_version=GRAPH_VERSION,
        toolset_version=TOOLSET_VERSION,
        prompt_snapshot={},
        model="pending",
        input_snapshot={"lead_id": lead.id, "message": inbound_text},
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
                status="draft",
            ))
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
