"""Additive evidence only: never infer a historical prompt or change routing."""
import logging
import uuid
from datetime import datetime, timezone
from app.core.config import settings

logger = logging.getLogger(__name__)


def dispatch_trace(conversation, lead, run_id, event_kind, proposed, final):
    return {
        "schema_version": "1.0", "trace_id": run_id or str(uuid.uuid4()),
        "agent_run_id": run_id, "company_id": conversation.company_id,
        "project_id": conversation.project_id, "lead_id": lead.id,
        "code_commit": settings.APP_COMMIT_SHA, "event_kind": event_kind,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "proposed_reply": proposed, "final_reply": final,
        "missing": ["code_commit"] if settings.APP_COMMIT_SHA == "unknown" else [],
    }


def capture_input(db, conversation):
    from app.modules.projects.models import Project
    from .commercial_context import build_commercial_context
    value = {"schema_version": "1.0", "code_commit": settings.APP_COMMIT_SHA,
             "company_id": conversation.company_id, "project_id": conversation.project_id,
             "lead_id": conversation.lead_id, "captured_at": datetime.now(timezone.utc).isoformat()}
    try:
        # A failed diagnostic SELECT must not poison the business transaction.
        with db.begin_nested():
            project = db.query(Project).filter(Project.id == conversation.project_id, Project.company_id == conversation.company_id).one()
            value["approved_context"] = build_commercial_context(db, project=project, company_id=conversation.company_id, lead_id=conversation.lead_id, channel=conversation.channel)
    except Exception:
        # Observability must not make a previously valid sales turn fail.
        logger.exception("Could not capture approved context for conversation %s", conversation.id)
        value["missing"] = ["approved_context"]
    return value


def capture_model_request(db, state, messages):
    """Persist the actual request before awaiting a fallible model provider.

    No provider credential is accepted by this function. A failed inference can
    therefore retain its real prompt/model instead of the settings at export time.
    """
    from .models import AgentRun
    run = db.query(AgentRun).filter(
        AgentRun.event_id == state.get("event_id"),
        AgentRun.conversation_id == state["conversation_id"],
    ).first()
    if run is None:
        return
    run.model = state["model"]
    run.prompt_configuration_id = state.get("prompt_configuration_id")
    run.prompt_snapshot = state["prompt_snapshot"]
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "graph_commercial_context": state["commercial_context"],
        "model_request": {"model": state["model"], "messages": messages,
                          "temperature": 0.2, "response_format": {"type": "json_object"}},
    }
    db.add(run)
    db.commit()
