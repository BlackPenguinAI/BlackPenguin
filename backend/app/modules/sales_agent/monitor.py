"""Read-only staff diagnostics. The only writes are immutable access/export audits."""
import hashlib
import re
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.companies.models import Company
from app.modules.projects.models import Project, SalesAssetShare
from app.modules.sales_crm.models import Lead
from app.modules.governance.models import HumanInterventionCase
from app.modules.governance.services import record_platform_event, record_export_event
from .models import SalesConversation, SalesConversationLeadContext, SalesMessage, AgentRun, OutboundMessage, SalesInboundJob, SalesFollowUpJob

def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(dependencies=[Depends(RoleChecker([UserRole.SUPERADMIN])), Depends(no_store)])
staff = RoleChecker([UserRole.SUPERADMIN])
SECRET = re.compile(r"password|secret|^authorization$|authorization_header|api.?key|access.?token|refresh.?token|credential|private.?key|token_hash|storage_path|^token$|cookie|^reasoning(?:_content|_text)?$|chain.?of.?thought|^analysis$|^thinking$|^thoughts$|^raw_(?:completion|model_output)$|thought_process|scratchpad|internal_monologue|(?:^|_)(?:reasoning|thinking|analysis)(?:_|$)", re.I)


def redact(value):
    if isinstance(value, dict):
        result={}
        for k,v in value.items():
            if k=='raw_response' and isinstance(v,str):
                import json
                try:
                    parsed=json.loads(v);clean=redact(parsed)
                    result[k]=v if clean==parsed else json.dumps(clean,ensure_ascii=False)
                except (ValueError,TypeError):result[k]='[REDACTED]'
            else:result[k]='[REDACTED]' if SECRET.search(k) else redact(v)
        return result
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[\w.\-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)[\"']?\s*[=:]\s*[\"']?)[^\s,;&\"']+", r"\1[REDACTED]", value)
        value = re.sub(r"\b(?:sk-|KEY)[A-Za-z0-9_-]{16,}", "[REDACTED]", value)
        value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", value)
        # Signed URLs, OAuth codes and public share capabilities are credentials too.
        value = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", value)
        value = re.sub(r"(https?://)[^/\s]+@", r"\1[REDACTED]@", value)
        return re.sub(r"(/api/v1/projects/(?:a|shared-assets)/)[A-Za-z0-9_-]+", r"\1[REDACTED]", value)
    return value


def row(item, exclude=()):
    values = {col.name: getattr(item, col.name) for col in item.__table__.columns if col.name not in exclude}
    # Database timestamps are UTC (legacy rows are timezone-naive). Be explicit
    # in downloads so analysts never interpret them as their browser timezone.
    return jsonable_encoder({key: ((value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat() if isinstance(value, datetime) else value) for key, value in values.items()})


class ChatExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["blackpenguin.chat-diagnostic/1.0"]
    exported_at: str
    timezone: Literal["UTC"]
    operational_context: dict = Field(default_factory=dict)
    scope: dict
    conversation: dict
    messages: list[dict]
    runs: list[dict]
    inbound_jobs: list[dict]
    outbound_deliveries: list[dict]
    follow_up_jobs: list[dict]
    pauses: list[dict]
    materials: list[dict]
    opportunity_contexts: list[dict]
    missing_evidence: list[str] = Field(default_factory=list)
    dialogue_states: list[dict] = Field(default_factory=list)
    dialogue_events: list[dict] = Field(default_factory=list)


def audit(db, actor, request, company_id, action, entity_id=None, payload=None):
    record_platform_event(db, actor=actor, company_id=company_id, event_type="monitor." + action,
                          entity_type="sales_conversation", entity_id=entity_id, payload=payload, request=request)
    db.commit()


def selected(db, company_id, project_id, lead_id, conversation_id):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.project_id == project_id).first()
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == company_id).first()
    conv = db.query(SalesConversation).filter(SalesConversation.id == conversation_id, SalesConversation.company_id == company_id).first()
    context = db.query(SalesConversationLeadContext).filter(SalesConversationLeadContext.conversation_id == conversation_id, SalesConversationLeadContext.lead_id == lead_id).first()
    if not lead or not project or not conv or (conv.lead_id != lead_id and not context):
        raise HTTPException(404, "Conversation not found in the selected Company, Project and Lead scope.")
    return conv


def message_query(db, conv, lead_id):
    query = db.query(SalesMessage).filter(SalesMessage.conversation_id == conv.id)
    has_context = db.query(SalesConversationLeadContext.id).filter(SalesConversationLeadContext.conversation_id == conv.id).first()
    # Unlike the active sales UI, staff can inspect old opportunities. Do not
    # invent attribution from a context timestamp that may have been reactivated.
    attributed_lead = SalesMessage.metadata_json["lead_id"].as_string()
    scope = attributed_lead == lead_id
    if not has_context and conv.lead_id == lead_id:
        scope = or_(scope, attributed_lead.is_(None), attributed_lead == "")
    return query.filter(scope)


def scoped_messages(db, conv, lead_id):
    messages = message_query(db, conv, lead_id).order_by(SalesMessage.created_at, SalesMessage.id).all()
    physical_count = db.query(SalesMessage.id).filter(SalesMessage.conversation_id == conv.id).count()
    return messages, physical_count


def explicit_run_leads(snapshot):
    """Explicit ownership wins over legacy fallback, including retry history."""
    if not isinstance(snapshot, dict):
        return set()
    owners = {value for value in (snapshot.get("lead_id"), (snapshot.get("turn_trace") or {}).get("lead_id")) if isinstance(value, str) and value}
    for key in ("input_snapshot", "historical_input"):
        owners.update(explicit_run_leads(snapshot.get(key)))
    for attempt in snapshot.get("trace_attempts") or []:
        owners.update(explicit_run_leads(attempt))
    return owners


def diagnostic(db, conv, company_id, project_id, lead_id):
    from .dialogue_models import SalesDialogueState, SalesDialogueEvent
    dialogue_scope = dict(company_id=company_id, project_id=project_id, lead_id=lead_id, conversation_id=conv.id)
    messages, physical_count = scoped_messages(db, conv, lead_id)
    ids = {m.id for m in messages}
    deliveries = db.query(OutboundMessage).filter(OutboundMessage.conversation_id == conv.id).all()
    linked_run_ids = {(m.metadata_json or {}).get("agent_run_id") for m in messages}
    attribution = db.query(SalesMessage.id, SalesMessage.metadata_json).filter(SalesMessage.conversation_id == conv.id).all()
    message_owners = {item.id: (item.metadata_json or {}).get("lead_id") for item in attribution}
    linked_owners = {}
    for item in attribution:
        metadata = item.metadata_json or {}
        if metadata.get("agent_run_id") and metadata.get("lead_id"):
            linked_owners.setdefault(metadata["agent_run_id"], set()).add(metadata["lead_id"])
    all_runs = db.query(AgentRun).filter(AgentRun.conversation_id == conv.id).order_by(AgentRun.started_at, AgentRun.id).all()
    no_contexts = not db.query(SalesConversationLeadContext.id).filter(SalesConversationLeadContext.conversation_id == conv.id).first()
    runs = []
    ownership_exclusions = []
    for run in all_runs:
        snapshot = run.input_snapshot or {}
        owners = explicit_run_leads(snapshot) | linked_owners.get(run.id, set())
        inbound_owner = message_owners.get(snapshot.get("message_id"))
        if inbound_owner:
            owners.add(inbound_owner)
        if owners:
            if owners == {lead_id}:
                runs.append(run)
            else:
                ownership_exclusions.append(run.id)
        elif run.id in linked_run_ids or snapshot.get("message_id") in ids or (no_contexts and conv.lead_id == lead_id):
            runs.append(run)
    run_ids = {r.id for r in runs}
    provider_ids = {m.provider_message_id for m in messages if m.provider_message_id}
    outbound_ids = {(m.metadata_json or {}).get("outbound_message_id") for m in messages}
    scoped_deliveries = [d for d in deliveries if d.id in outbound_ids or d.agent_run_id in run_ids or d.provider_message_id in provider_ids]
    missing = []
    if ownership_exclusions:
        missing.append("Executions with other-opportunity or conflicting explicit attribution excluded; legacy ownership fallback was not applied to them.")
    if physical_count != len(messages):
        missing.append("Other-opportunity or unattributed messages excluded; physical thread is not the selected opportunity.")
    if any(not (m.metadata_json or {}).get("lead_id") for m in messages):
        missing.append("Legacy messages lack explicit opportunity attribution; scoped by legacy conversation ownership only.")
    run_values = []
    for r in runs:
        item = row(r)
        trace = (r.input_snapshot or {}).get("turn_trace") or {}
        absent = [key for key in ("code_commit", "approved_context") if not trace.get(key) or trace.get(key) == "unknown"]
        if not r.prompt_snapshot and not r.model.startswith("deterministic/"):
            absent.append("applied_prompt_snapshot")
        if not r.model.startswith("deterministic/") and not (r.input_snapshot or {}).get("graph_commercial_context"):
            absent.append("actual_graph_commercial_context")
        if r.model in {"unknown", "pending"}:
            absent.append("applied_model")
        item["missing_evidence"] = absent
        if absent:
            missing.append("Run " + r.id + ": " + ", ".join(absent))
        run_values.append(item)
    for m in messages:
        if m.direction == "outbound" and not (m.metadata_json or {}).get("turn_trace"):
            missing.append("Message " + m.id + ": historical dispatch trace unavailable")
    jobs = db.query(SalesInboundJob).filter(SalesInboundJob.message_id.in_(ids)).all() if ids else []
    followups = db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id == conv.id).all()
    followup_ids = {(r.input_snapshot or {}).get("follow_up_job_id") for r in runs}
    if not no_contexts:
        followups = [j for j in followups if j.id in followup_ids]
        missing.append("Unattributed follow-up jobs excluded from context-aware threads.")
    pauses = db.query(HumanInterventionCase).filter(HumanInterventionCase.conversation_id == conv.id, HumanInterventionCase.lead_id == lead_id, HumanInterventionCase.company_id == company_id, HumanInterventionCase.project_id == project_id).all()
    materials = db.query(SalesAssetShare).filter(SalesAssetShare.company_id == company_id, SalesAssetShare.project_id == project_id, SalesAssetShare.lead_id == lead_id).all()
    contexts = db.query(SalesConversationLeadContext).filter(SalesConversationLeadContext.conversation_id == conv.id, SalesConversationLeadContext.lead_id == lead_id).all()
    referenced_shares = {sid for m in messages for sid in ((m.metadata_json or {}).get("sales_asset_share_ids") or [])}
    # The live conversation may now point to a different opportunity. Its pause
    # state is labelled as current physical-thread state, never historical fact.
    conversation = row(conv, ("provider_thread_key", "lead_id", "project_id", "campaign_id", "pending_asset_id"))
    conversation["state_scope"] = "current_physical_thread_not_historical"
    from .operational_context import snapshot
    operational=snapshot(db,conv) if (conv.company_id,conv.project_id,conv.lead_id)==(company_id,project_id,lead_id) else {'scope_limited':True,'historical':True}
    result = ChatExport(operational_context=operational,schema_version="blackpenguin.chat-diagnostic/1.0", exported_at=datetime.now(timezone.utc).isoformat(), timezone="UTC",
        scope={"company_id":company_id, "project_id":project_id, "lead_id":lead_id, "conversation_id":conv.id}, conversation=conversation,
        messages=[row(m) for m in messages], runs=run_values, inbound_jobs=[row(j) for j in jobs],
        outbound_deliveries=[row(d, ("recipient",)) for d in scoped_deliveries],
        follow_up_jobs=[row(j) for j in followups], pauses=[row(p) for p in pauses],
        materials=[row(m, ("token_hash", "target_url")) for m in materials if m.id in referenced_shares or m.agent_run_id in run_ids or m.outbound_message_id in {d.id for d in scoped_deliveries}],
        opportunity_contexts=[row(c) for c in contexts], missing_evidence=missing,
        dialogue_states=[row(s) for s in db.query(SalesDialogueState).filter_by(**dialogue_scope).all()],
        dialogue_events=[row(e) for e in db.query(SalesDialogueEvent).filter_by(**dialogue_scope).order_by(SalesDialogueEvent.revision).all()])
    return ChatExport.model_validate(redact(result.model_dump(mode="json")))


@router.get("/companies")
def companies(request: Request, db: Session = Depends(get_db), actor: User = Depends(staff), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    items = db.query(Company).order_by(Company.name, Company.id).offset(offset).limit(limit + 1).all()
    audit(db, actor, request, None, "companies", payload={"offset":offset, "limit":limit})
    return {"items":[{"id":i.id, "name":i.name} for i in items[:limit]], "has_more":len(items)>limit}


@router.get("/projects")
def projects(company_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(staff)):
    if not db.query(Company.id).filter(Company.id == company_id).first():
        raise HTTPException(404, "Company not found.")
    items = db.query(Project).filter(Project.company_id == company_id).order_by(Project.name, Project.id).all()
    audit(db, actor, request, company_id, "projects")
    return [{"id":i.id, "name":i.name} for i in items]


@router.get("/leads")
def leads(company_id: str, project_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(staff), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    if not db.query(Project.id).filter(Project.id == project_id, Project.company_id == company_id).first():
        raise HTTPException(404, "Project not found in selected Company.")
    items = db.query(Lead).filter(Lead.company_id == company_id, Lead.project_id == project_id).order_by(Lead.full_name, Lead.id).offset(offset).limit(limit + 1).all()
    audit(db, actor, request, company_id, "leads", payload={"project_id":project_id, "offset":offset})
    return {"items":[{"id":i.id, "name":i.full_name} for i in items[:limit]], "has_more":len(items)>limit}


@router.get("/conversations")
def conversations(company_id: str, project_id: str, lead_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(staff)):
    if not db.query(Lead.id).filter(Lead.id == lead_id, Lead.company_id == company_id, Lead.project_id == project_id).first():
        raise HTTPException(404, "Lead not found in selected scope.")
    old = db.query(SalesConversationLeadContext.conversation_id).filter(SalesConversationLeadContext.lead_id == lead_id)
    items = db.query(SalesConversation).filter(SalesConversation.company_id == company_id, or_(SalesConversation.lead_id == lead_id, SalesConversation.id.in_(old))).order_by(SalesConversation.created_at, SalesConversation.id).all()
    audit(db, actor, request, company_id, "conversations", payload={"project_id":project_id, "lead_id":lead_id})
    return [{"id":i.id, "channel":i.channel, "provider":i.provider, "is_paused":i.is_paused} for i in items]


@router.get("/conversations/{conversation_id}")
def detail(conversation_id: str, company_id: str, project_id: str, lead_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(staff), after: str | None = None, limit: int = Query(100, ge=1, le=200)):
    from .dialogue_models import SalesDialogueEvent
    conv = selected(db, company_id, project_id, lead_id, conversation_id)
    query = message_query(db, conv, lead_id)
    if after:
        cursor = query.filter(SalesMessage.id == after).first()
        if not cursor:
            raise HTTPException(409, "Message cursor changed or is outside this opportunity. Reload the conversation.")
        query = query.filter(or_(SalesMessage.created_at > cursor.created_at, and_(SalesMessage.created_at == cursor.created_at, SalesMessage.id > cursor.id)))
    messages = query.order_by(SalesMessage.created_at, SalesMessage.id).limit(limit + 1).all()
    batch = messages[:limit]
    audit(db, actor, request, company_id, "read", conversation_id, {"project_id":project_id, "lead_id":lead_id, "after":after})
    from .operational_context import snapshot
    return redact({"operational_context":snapshot(db,conv) if (conv.company_id,conv.project_id,conv.lead_id)==(company_id,project_id,lead_id) else {"scope_limited":True,"historical":True},"messages":[row(m) for m in batch], "next_cursor":batch[-1].id if batch else after,
        "dialogue_events":[row(e) for e in db.query(SalesDialogueEvent).filter_by(company_id=company_id,
            project_id=project_id,lead_id=lead_id,conversation_id=conv.id).order_by(SalesDialogueEvent.revision.desc()).limit(20).all()],
        "has_more":len(messages)>limit, "is_paused":conv.is_paused, "pause_reason":conv.pause_reason,
        "delivery_statuses":[{"message_id":m.id,"status":m.status} for m in message_query(db, conv, lead_id).with_entities(SalesMessage.id, SalesMessage.status).filter(SalesMessage.direction == "outbound").order_by(SalesMessage.created_at, SalesMessage.id).all()]})


@router.get("/conversations/{conversation_id}/export")
def export(conversation_id: str, company_id: str, project_id: str, lead_id: str, request: Request, db: Session = Depends(get_db), actor: User = Depends(staff)):
    conv = selected(db, company_id, project_id, lead_id, conversation_id)
    # Recorded evidence only. No current AI configuration is substituted for
    # missing historical settings, and no provider is contacted.
    value = diagnostic(db, conv, company_id, project_id, lead_id)
    content = value.model_dump_json(indent=2).encode()
    record_export_event(db, actor=actor, export_type="staff_chat_diagnostic", filters=value.scope, record_count=len(value.messages), content=content, request=request)
    audit(db, actor, request, company_id, "export", conversation_id, {**value.scope,"sha256":hashlib.sha256(content).hexdigest()})
    return Response(content, media_type="application/json", headers={"Content-Disposition":f'attachment; filename="chat-{conv.id}.json"', "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})


@router.get("/export-schema")
def export_schema():
    return ChatExport.model_json_schema()
