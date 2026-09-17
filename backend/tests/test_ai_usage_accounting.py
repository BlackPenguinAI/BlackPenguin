import asyncio
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.usage import LLMUsageContext, record_openrouter_usage
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_agent.models import AgentRun, SalesConversation
from app.modules.sales_crm.models import Lead
from app.modules.users.models import User, UserRole


class _ProviderResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "generation-1",
            "model": "openai/gpt-test",
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15, "cost": 0.004},
        }


class _ProviderClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        return _ProviderResponse()


def test_openrouter_client_forwards_real_provider_usage_without_changing_text_contract():
    context = LLMUsageContext(company_id="company-1", user_id="user-1", feature="test")
    with patch("app.integrations.openrouter_client.httpx.AsyncClient", return_value=_ProviderClient()), patch(
        "app.integrations.openrouter_client.record_openrouter_usage",
    ) as recorder:
        content = asyncio.run(generate_llm_response("key", "model", [{"role": "user", "content": "Hi"}], usage_context=context))

    assert content == "Hello"
    recorder.assert_called_once()
    assert recorder.call_args.kwargs["usage"]["total_tokens"] == 15
    assert recorder.call_args.kwargs["context"] == context


def test_usage_accounting_updates_company_user_and_agent_run_atomically(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.modules.ai_core.usage.SessionLocal", factory)
    db = factory()
    company = Company(name="Usage Tenant", is_active=True)
    user = User(company=company, email="usage@example.com", hashed_password="x", role=UserRole.ADMIN)
    db.add_all([company, user]); db.flush()
    project = Project(company_id=company.id, name="Usage Project")
    db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Usage Lead", phone="+15550001234")
    db.add(lead); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id, channel="simulation",
    )
    db.add(conversation); db.flush()
    run = AgentRun(
        conversation_id=conversation.id, event_id="usage-event", graph_version="v1", toolset_version="v1",
        prompt_snapshot={}, model="pending", input_snapshot={}, output_snapshot={}, token_usage={},
    )
    db.add(run); db.commit()

    context = LLMUsageContext(
        company_id=company.id, user_id=user.id, project_id=project.id,
        feature="sales_agent", agent_run_event_id="usage-event",
    )
    record_openrouter_usage(
        context=context, model="openai/gpt-test", response_id="generation-1",
        usage={"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125, "cost": 0.0125},
    )

    db.expire_all()
    assert db.get(Company, company.id).ai_tokens_used == 125
    assert db.get(Company, company.id).ai_cost_usd == 0.0125
    assert db.get(User, user.id).ai_tokens_used == 125
    stored_run = db.query(AgentRun).filter_by(event_id="usage-event").one()
    assert stored_run.token_usage["total_tokens"] == 125
    assert stored_run.token_usage["cost"] == 0.0125
    assert stored_run.estimated_cost_usd == "0.0125000000"
    db.close(); engine.dispose()
