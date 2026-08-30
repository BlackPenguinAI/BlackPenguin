from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.companies.models import Company
from app.modules.projects import asset_share_service
from app.modules.projects.models import Project, ProjectPropertyType, ProjectUnit
from app.modules.sales_crm.models import Lead, LeadContact
from .segment_strategies import BASE_SEGMENT_GUARDRAIL, STRATEGY_VERSION

from .models import SalesMessage
from .state import SalesAgentState


GRAPH_VERSION = "sales-v1"
TOOLSET_VERSION = "sales-tools-v1"
PLATFORM_GUARDRAILS = (
    "Never cross Company boundaries. Never invent prices, inventory or appointment slots. "
    "Respect consent and opt-out. Demo data may be used only in simulation and can never be dispatched. "
    "Return only JSON matching the requested contract."
)


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def build_sales_graph(db: Session):
    async def validate_event(state: SalesAgentState) -> dict[str, Any]:
        lead = db.query(Lead).filter(
            Lead.id == state["lead_id"],
            Lead.company_id == state["company_id"],
            Lead.project_id == state["project_id"],
        ).first()
        project = db.query(Project).filter(
            Project.id == state["project_id"],
            Project.company_id == state["company_id"],
        ).first()
        violations: list[str] = []
        if not lead or not project:
            violations.append("tenant_scope_mismatch")
        elif project.is_demo and state.get("mode") != "simulation":
            violations.append("demo_external_contact_forbidden")
        if lead and lead.is_opt_out:
            violations.append("lead_opted_out")
        return {"policy_violations": violations, "requires_human": bool(violations)}

    async def load_context(state: SalesAgentState) -> dict[str, Any]:
        company = db.query(Company).filter(Company.id == state["company_id"]).one()
        project = db.query(Project).filter(Project.id == state["project_id"], Project.company_id == state["company_id"]).one()
        lead = db.query(Lead).filter(Lead.id == state["lead_id"], Lead.company_id == state["company_id"]).one()
        contact = db.query(LeadContact).filter(
            LeadContact.id == lead.contact_id,
            LeadContact.company_id == state["company_id"],
        ).first() if lead.contact_id else None
        profile = project.profile
        confirmed = {}
        if profile:
            confirmed = {
                key: value for key, value in (profile.profile_data or {}).items()
                if (profile.field_states or {}).get(key, {}).get("status") in {"confirmed", "corrected_by_user", "not_applicable"}
            }
        units = db.query(ProjectUnit).filter(ProjectUnit.project_id == project.id).all()
        property_types = db.query(ProjectPropertyType).filter(
            ProjectPropertyType.project_id == project.id,
            ProjectPropertyType.review_status == "confirmed",
        ).all()
        structured_inventory = []
        for item in property_types:
            links = [
                asset_share_service.issue(
                    db, company_id=company.id, project_id=project.id, lead_id=lead.id, source_id=media.source_id,
                )
                for media in sorted(item.media, key=lambda value: value.sort_order)[:6]
            ]
            structured_inventory.append({
                "property_type": item.name, "description": item.description,
                "bedrooms": item.bedrooms, "bathrooms": item.bathrooms,
                "area_min": float(item.area_min) if item.area_min is not None else None,
                "area_max": float(item.area_max) if item.area_max is not None else None,
                "area_unit": item.area_unit, "available_units": item.available_units,
                "starting_price": float(item.starting_price) if item.starting_price is not None else None,
                "maximum_price": float(item.maximum_price) if item.maximum_price is not None else None,
                "currency": item.currency, "features": item.features or [],
                "inventory_updated_at": item.inventory_updated_at, "image_links": links,
            })
        if structured_inventory:
            db.commit()
        history = db.query(SalesMessage).filter(
            SalesMessage.conversation_id == state["conversation_id"],
        ).order_by(SalesMessage.created_at.asc()).all()
        return {
            "company_context": {"id": company.id, "name": company.name},
            "project_context": {"id": project.id, "name": project.name, "is_demo": project.is_demo, "profile": confirmed},
            "inventory_context": structured_inventory or [
                {"unit_code": unit.unit_code, "typology": unit.typology, "bedrooms": unit.bedrooms,
                 "bathrooms": unit.bathrooms, "price": float(unit.list_price) if unit.list_price is not None else None,
                 "currency": unit.currency, "status": unit.status}
                for unit in units
            ],
            "lead_context": {
                "id": lead.id, "name": lead.full_name, "stage": lead.funnel_stage.value,
                "intent_score": float(lead.intent_score or 0), "consent_status": lead.consent_status,
                "intent_tier": lead.intent_tier, "pipeline_stage": lead.pipeline_stage,
                "assigned_segment": lead.assigned_segment,
                "segment_strategy": None,
                "segment_strategy_version": STRATEGY_VERSION,
                "segment_guardrail": BASE_SEGMENT_GUARDRAIL,
                "qualification_summary": lead.qualification_summary,
                "meta_form_data": lead.meta_form_data or {},
                "prior_history_for_phone": contact.previous_projects if contact else [],
            },
            "conversation_history": [
                {"role": message.role, "content": message.content}
                for message in history[-20:]
            ],
        }

    async def resolve_prompt(state: SalesAgentState) -> dict[str, Any]:
        config = get_ai_config(db, None)
        agent = config.agent_ventas or {}
        segment = (state.get("lead_context") or {}).get("assigned_segment") or ""
        playbook = {
            "stage_prompts": agent.get("stage_prompts", {}),
            "segment_prompt": (agent.get("segment_prompts", {}) or {}).get(segment, ""),
            "objection_prompts": agent.get("objection_prompts", {}),
            "sms_templates": agent.get("sms_templates", {}),
        }
        return {
            "prompt_configuration_id": config.id,
            "prompt_snapshot": {
                "platform_guardrails": PLATFORM_GUARDRAILS,
                "system_prompt": agent.get("system_prompt", ""),
                "protocol_prompt": agent.get("protocol_prompt", ""),
                "guardrails_prompt": agent.get("guardrails_prompt", ""),
                "published_playbook": "PUBLISHED PLAYBOOK:\n" + json.dumps(playbook, ensure_ascii=False),
            },
            "model": agent.get("model") or "openai/gpt-4o-mini",
        }

    async def reason(state: SalesAgentState) -> dict[str, Any]:
        # Provider keys may remain Company-scoped, while the published Sales
        # prompt pack above is governed globally by Black Penguin.
        config = get_ai_config(db, state["company_id"])
        if not config.openrouter_api_key:
            if state.get("mode") == "simulation":
                return {
                    "intent": "demo_follow_up",
                    "proposed_actions": [{"type": "ask_qualification_question"}],
                    "proposed_reply": (
                        "Thanks for sharing that. What matters most for your next home: "
                        "location, number of bedrooms, budget, or move-in timing?"
                    ),
                    "requires_human": False,
                    "error_code": None,
                }
            return {"requires_human": True, "error_code": "missing_openrouter_key", "proposed_reply": None}
        contract = {
            "reply": "string",
            "intent": "string",
            "extracted_facts": [],
            "proposed_actions": [],
            "requires_human": False,
            "reason": "string",
        }
        messages = [
            {"role": "system", "content": "\n\n".join(state["prompt_snapshot"].values())},
            {"role": "system", "content": "RUNTIME CONTEXT:\n" + json.dumps({
                "company": state["company_context"], "project": state["project_context"],
                "inventory": state["inventory_context"], "lead": state["lead_context"],
                "event_kind": state.get("event_kind", "lead_message"),
                "allowed_actions": ["answer_question", "ask_qualification_question", "search_inventory", "request_available_slots", "offer_appointment", "schedule_follow_up", "request_human_review"],
                "contract": contract,
            }, ensure_ascii=False, default=str)},
        ]
        history = state.get("conversation_history", [])
        for message in history[:-1]:
            if message.get("role") in {"user", "assistant"} and message.get("content"):
                messages.append({"role": message["role"], "content": message["content"]})
        messages.append({"role": "user", "content": state["inbound_text"]})
        raw = await generate_llm_response(
            config.openrouter_api_key,
            state["model"],
            messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            raise_on_error=True,
        )
        value = _json_object(raw)
        return {
            "intent": value.get("intent"),
            "extracted_facts": value.get("extracted_facts") if isinstance(value.get("extracted_facts"), list) else [],
            "proposed_actions": value.get("proposed_actions") if isinstance(value.get("proposed_actions"), list) else [],
            "proposed_reply": value.get("reply") if isinstance(value.get("reply"), str) else None,
            "requires_human": bool(value.get("requires_human")),
            "error_code": None if value.get("reply") else "invalid_model_contract",
        }

    async def validate_output(state: SalesAgentState) -> dict[str, Any]:
        violations = list(state.get("policy_violations", []))
        allowed = {"answer_question", "ask_qualification_question", "search_inventory", "request_available_slots", "offer_appointment", "schedule_follow_up", "request_human_review"}
        for action in state.get("proposed_actions", []):
            if not isinstance(action, dict) or action.get("type") not in allowed:
                violations.append("unsupported_action")
        if not state.get("proposed_reply"):
            violations.append("missing_reply")
        return {"policy_violations": sorted(set(violations)), "requires_human": bool(violations) or state.get("requires_human", False)}

    def after_validation(state: SalesAgentState) -> str:
        return "stop" if state.get("policy_violations") else "continue"

    graph = StateGraph(SalesAgentState)
    graph.add_node("validate_event", validate_event)
    graph.add_node("load_context", load_context)
    graph.add_node("resolve_prompt", resolve_prompt)
    graph.add_node("reason", reason)
    graph.add_node("validate_output", validate_output)
    graph.add_edge(START, "validate_event")
    graph.add_conditional_edges("validate_event", after_validation, {"stop": END, "continue": "load_context"})
    graph.add_edge("load_context", "resolve_prompt")
    graph.add_edge("resolve_prompt", "reason")
    graph.add_edge("reason", "validate_output")
    graph.add_edge("validate_output", END)
    return graph.compile()
