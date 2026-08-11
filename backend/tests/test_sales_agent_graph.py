import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.base  # noqa: F401 - registers every model in metadata
from app.db.postgres import Base
from app.modules.ai_core.models import AIConfiguration
from app.modules.companies.models import Company
from app.modules.demo_projects.service import provision_demo_project
from app.modules.sales_agent.models import OutboundMessage
from app.modules.sales_agent.service import simulate_turn
from app.modules.sales_crm.models import Lead
from app.modules.users.models import User, UserRole


def test_langgraph_simulation_creates_a_draft_without_dispatching():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    company = Company(name="Test Company")
    db.add(company)
    db.flush()
    admin = User(
        company_id=company.id,
        email="admin@example.com",
        hashed_password="test",
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.flush()
    project = provision_demo_project(db, company_id=company.id, approved_by_user_id=admin.id)
    db.add(AIConfiguration(
        company_id=company.id,
        openrouter_api_key="test",
        agent_ventas={
            "model": "test/model",
            "system_prompt": "Help the lead.",
            "protocol_prompt": "Qualify one field at a time.",
            "guardrails_prompt": "Use confirmed facts only.",
        },
    ))
    db.commit()
    lead = db.query(Lead).filter(Lead.project_id == project.id).first()
    llm_json = (
        '{"reply":"What layout do you prefer?","intent":"qualification",'
        '"extracted_facts":[],"proposed_actions":[{"type":"ask_qualification_question"}],'
        '"requires_human":false,"reason":"Need preference"}'
    )

    with patch(
        "app.modules.sales_agent.graph.generate_llm_response",
        new=AsyncMock(return_value=llm_json),
    ):
        result = asyncio.run(simulate_turn(
            db,
            company_id=company.id,
            lead_id=lead.id,
            inbound_text="I am interested.",
        ))

    assert result["status"] == "completed"
    assert result["draft_id"]
    draft = db.query(OutboundMessage).one()
    assert draft.status == "draft"
    assert draft.sent_at is None
