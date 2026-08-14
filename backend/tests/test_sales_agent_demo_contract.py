from pathlib import Path
import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

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
    assert "_validate_existing_table" in source
    assert "op.drop_table" not in source


def test_agent_migration_is_repeatable_and_downgrade_preserves_adopted_tables(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260814_sales_agent_demo.py"
    spec = importlib.util.spec_from_file_location("sales_agent_demo_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)

        migration.upgrade()
        migration.upgrade()

        expected = set(migration.TABLE_COLUMNS)
        assert expected.issubset(set(sa.inspect(connection).get_table_names()))

        migration.downgrade()
        assert expected.issubset(set(sa.inspect(connection).get_table_names()))
        registered = connection.execute(
            sa.text("SELECT COUNT(*) FROM schema_versions WHERE version = :version"),
            {"version": migration.revision},
        ).scalar_one()
        assert registered == 0
