from pathlib import Path

from app.modules.sales_agent.graph import PLATFORM_GUARDRAILS
from app.modules.sales_agent.schemas import ConversationAction, SimulationRequest


def test_simulation_message_and_actions_are_constrained():
    assert SimulationRequest(lead_id="lead", message="Hello").message == "Hello"
    assert ConversationAction(action="pause").action == "pause"
    assert ConversationAction(action="resume").action == "resume"
    assert "Demo data" in PLATFORM_GUARDRAILS


def test_agent_migration_contains_persistent_conversation_tables():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "20260814_sales_agent_demo.py"
    source = migration.read_text()
    for table in ("sales_conversations", "sales_messages", "agent_runs", "outbound_messages"):
        assert f'"{table}"' in source
