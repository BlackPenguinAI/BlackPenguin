"""P05 global-only Hermes Staff registry, migration and policy contract.

Runs without internet, OpenRouter or production PostgreSQL. Unlike the
production integration, the ORM fixture is a minimal SQLite model namespace.
"""
from __future__ import annotations
import importlib
import runpy
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, String, create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker


@pytest.fixture(scope='module')
def unit():
    base = declarative_base()
    pg = types.ModuleType('app.db.postgres')
    pg.Base = base
    sentinel = object()
    targets = ('app.modules.hermes_sales_core.staff_models',
               'app.modules.hermes_sales_core.staff_config',
               'app.modules.hermes_sales_core.config',
               'app.modules.hermes_sales_core.tool_schemas')
    original = {name: sys.modules.get(name, sentinel) for name in (*targets, 'app.db.postgres')}
    for name in targets:
        sys.modules.pop(name, None)
    sys.modules['app.db.postgres'] = pg
    class User(base):
        __tablename__ = 'users'
        id = Column(String(36), primary_key=True)
    from app.modules.hermes_sales_core import staff_config as control
    from app.modules.hermes_sales_core import staff_models as models
    yield SimpleNamespace(Base=base, User=User, control=control, models=models)
    for name in targets:
        sys.modules.pop(name, None)
    for name, value in original.items():
        if value is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = value


@pytest.fixture
def registry(unit):
    engine = create_engine('sqlite:///:memory:')
    unit.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    session.add(unit.User(id='staff-a'))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_initial_configuration_is_global_english_and_disabled(unit, registry):
    current = unit.control.snapshot(registry)
    assert current['configuration_scope'] == 'global'
    assert current['configuration']['language'] == 'en'
    assert current['configuration']['engine'] == 'hermes-agent'
    assert current['configuration']['enabled'] is False
    assert current['runtime_connected_to_live'] is False
    assert not current['published_version_id']


def test_rejects_spanish_and_company_specific_overrides(unit):
    row = unit.control.baseline()
    row['language'] = 'es'
    with pytest.raises(ValidationError):
        unit.control.normalized(row)
    row = unit.control.baseline()
    row['company_id'] = 'company-a'
    with pytest.raises(ValidationError):
        unit.control.normalized(row)


def test_model_must_be_allowed_and_belongs_to_openrouter(unit):
    row = unit.control.baseline()
    row['model'] = 'nonexistent/model'
    with pytest.raises(ValidationError):
        unit.control.normalized(row)
    row['allowed_models'] = ['nonexistent/model']
    assert unit.control.normalized(row)['model'] == 'nonexistent/model'


def test_duplicate_models_rejected(unit):
    row = unit.control.baseline()
    row['allowed_models'] *= 2
    with pytest.raises(ValidationError):
        unit.control.normalized(row)


def test_unknown_tool_denied(unit):
    row = unit.control.baseline()
    row['enabled_tools'] = ['terminal']
    with pytest.raises(ValidationError):
        unit.control.normalized(row)


def test_tool_allowlist_may_be_restricted(unit):
    row = unit.control.baseline()
    row['enabled_tools'] = ['search_properties']
    assert unit.control.normalized(row)['enabled_tools'] == ['search_properties']


def test_cannot_raise_sdk_max_iterations(unit):
    row = unit.control.baseline()
    row['max_iterations'] = 13
    with pytest.raises(ValidationError):
        unit.control.normalized(row)
    row['max_iterations'] = True
    with pytest.raises(ValidationError):
        unit.control.normalized(row)


def test_provider_and_engine_are_fixed(unit):
    row = unit.control.baseline()
    row['provider'] = 'local'
    with pytest.raises(ValidationError):
        unit.control.normalized(row)
    row = unit.control.baseline()
    row['engine'] = 'langgraph'
    with pytest.raises(ValidationError):
        unit.control.normalized(row)


def test_publishing_is_global_and_audited(unit, registry):
    draft = unit.control.create_draft(registry, configuration=unit.control.baseline(),
                                      note='First global Hermes release', actor_id='staff-a')
    assert draft['version'] == 1
    assert draft['is_published'] is False
    published = unit.control.publish(registry, version_id=draft['id'], actor_id='staff-a')
    assert published['published_version_id'] == draft['id']
    assert published['revision'] == 1
    assert unit.control.versions(registry)['total'] == 1


def test_multiple_drafts_do_not_publish_automatically(unit, registry):
    first = unit.control.create_draft(registry, configuration=unit.control.baseline(), note='first', actor_id='staff-a')
    unit.control.publish(registry, version_id=first['id'], actor_id='staff-a')
    second = unit.control.create_draft(registry, configuration=unit.control.baseline(), note='second', actor_id='staff-a')
    snap = unit.control.snapshot(registry)
    assert second['version'] == 2
    assert snap['published_version_id'] == first['id']


def test_restore_creates_new_published_version(unit, registry):
    one = unit.control.create_draft(registry, configuration=unit.control.baseline(), note='baseline', actor_id='staff-a')
    unit.control.publish(registry, version_id=one['id'], actor_id='staff-a')
    changed = unit.control.baseline()
    changed['max_iterations'] = 5
    two = unit.control.create_draft(registry, configuration=changed, note='adjusted', actor_id='staff-a')
    unit.control.publish(registry, version_id=two['id'], actor_id='staff-a')
    restored = unit.control.restore(registry, version_id=one['id'], actor_id='staff-a')
    assert restored['revision'] == 3
    assert restored['configuration']['max_iterations'] == 12
    assert restored['published_version_id'] not in {one['id'], two['id']}
    assert unit.control.versions(registry)['total'] == 3
    assert sum(bool(v['is_published']) for v in unit.control.versions(registry)['items']) == 1


def test_no_credentials_in_published_configuration(unit, registry):
    row = unit.control.baseline()
    row['api_key'] = 'SECRET_TEST_KEY'
    with pytest.raises(ValidationError):
        unit.control.create_draft(registry, configuration=row, note='', actor_id='staff-a')
    assert 'SECRET_TEST_KEY' not in str(unit.control.snapshot(registry))


def test_live_settings_fail_closed_without_published_enabled_version(unit, registry):
    with pytest.raises(PermissionError, match='not enabled'):
        unit.control.settings_for_turn(registry)


def test_missing_version_does_not_modify_registry(unit, registry):
    with pytest.raises(LookupError):
        unit.control.publish(registry, version_id='nonexistent', actor_id='staff-a')
    registry.rollback()
    assert unit.control.versions(registry)['total'] == 0


def test_hermes_migration_creates_both_tables_and_has_correct_parent():
    path = Path(__file__).resolve().parents[1] / 'alembic' / 'versions' / '20261125_hermes_sales_p05.py'
    namespace = runpy.run_path(str(path))
    assert namespace['down_revision'] == '20261125_hermes_sales_p04'
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = create_engine('sqlite:///:memory:')
    with engine.connect() as conn:
        migration = MigrationContext.configure(conn)
        namespace['upgrade'].__globals__['op'] = Operations(migration)
        namespace['downgrade'].__globals__['op'] = Operations(migration)
        namespace['upgrade']()
        assert {'hermes_global_settings', 'hermes_global_versions'} <= set(inspect(conn).get_table_names())
        namespace['downgrade']()
        assert not {'hermes_global_settings', 'hermes_global_versions'} & set(inspect(conn).get_table_names())
    engine.dispose()
