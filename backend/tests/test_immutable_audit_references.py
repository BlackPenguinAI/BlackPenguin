import importlib.util
from pathlib import Path

from app.modules.governance.models import DataExportAuditEvent, PlatformAuditEvent


def _migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20261015_immutable_audit_references.py"
    )
    spec = importlib.util.spec_from_file_location("immutable_audit_references", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_immutable_audit_subjects_are_historical_identifiers():
    for model in (PlatformAuditEvent, DataExportAuditEvent):
        for column_name in ("company_id", "actor_user_id"):
            column = model.__table__.c[column_name]
            assert column.nullable is True
            assert not column.foreign_keys
            assert column.index is True


def test_audit_reference_migration_is_current_and_covers_both_audit_tables():
    migration = _migration()

    assert migration.revision == "20261015_audit_refs"
    assert migration.down_revision == "20261014_company_timezone"
    assert migration.AUDIT_REFERENCES == (
        (
            "platform_audit_events",
            "platform_audit_events_company_id_fkey",
            "company_id",
            "companies",
        ),
        (
            "platform_audit_events",
            "platform_audit_events_actor_user_id_fkey",
            "actor_user_id",
            "users",
        ),
        (
            "data_export_audit_events",
            "data_export_audit_events_company_id_fkey",
            "company_id",
            "companies",
        ),
        (
            "data_export_audit_events",
            "data_export_audit_events_actor_user_id_fkey",
            "actor_user_id",
            "users",
        ),
    )


def test_upgrade_drops_discovered_constraint_names_and_is_repeatable(monkeypatch):
    migration = _migration()
    existing = {
        (table, column, referred_table): expected_name
        for table, expected_name, column, referred_table in migration.AUDIT_REFERENCES
    }
    dropped: list[tuple[str, str, str]] = []

    monkeypatch.setattr(migration, "_tables", lambda: {
        "platform_audit_events", "data_export_audit_events",
    })
    monkeypatch.setattr(
        migration,
        "_matching_constraint",
        lambda table, column, referred_table: existing.get((table, column, referred_table)),
    )

    def drop_constraint(name, table, *, type_):
        dropped.append((name, table, type_))
        for key, value in tuple(existing.items()):
            if value == name and key[0] == table:
                del existing[key]

    monkeypatch.setattr(migration.op, "drop_constraint", drop_constraint)

    migration.upgrade()
    migration.upgrade()

    assert dropped == [
        (expected_name, table, "foreignkey")
        for table, expected_name, _column, _referred_table in migration.AUDIT_REFERENCES
    ]
