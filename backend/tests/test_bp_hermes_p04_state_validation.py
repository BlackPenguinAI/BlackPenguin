"""P04 durable evidence checks. SQLite ORM stand-ins; no external providers."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from test_bp_hermes_p03_state import orm, db, SCOPE


def _offer(orm):
    state=orm.store.blank_state(SCOPE)
    state['last_slot_search']={
        'project_id':SCOPE.project_id,'unit_id':'H-201',
        'proposal_id':'offer-a','timezone':'America/Lima',
        'options':[{'date':'2026-11-27','start_time':'10:00',
                    'starts_at_utc':'2026-11-27T15:00:00+00:00'}],
        'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),
    }
    return state


def test_rejects_a_slot_offer_from_a_foreign_project(orm,db):
    state=_offer(orm)
    state['last_slot_search']['project_id']='proj-b'
    with pytest.raises(PermissionError,match='another project'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='bad-slot-scope',state=state)


def test_rejects_foreign_unit_in_slot_offer(orm,db):
    state=_offer(orm)
    state['last_slot_search']['unit_id']='unit-b'
    with pytest.raises(PermissionError,match='foreign inventory'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='bad-slot-unit',state=state)


def test_slot_offer_must_be_associated_with_a_sent_reply(orm,db):
    state=_offer(orm)
    state['last_slot_search']['source_reply_message_id']='unsent-a'
    with pytest.raises(PermissionError,match='actual delivered reply'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='bad-slot-reply',state=state)


def test_recap_reference_not_valid_if_exact_date_hour_property_not_shown(orm,db):
    state=_offer(orm)
    state['confirmation_request']={
        'id':'recap-a','kind':'book','status':'awaiting_confirmation',
        'unit_id':'H-201','date':'2026-11-27','start_time':'10:00',
        'recap_message_id':'reply-a',
    }
    with pytest.raises(PermissionError,match='exact appointment details'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='bad-recap',state=state)


def test_valid_exact_delivered_recap_is_persisted(orm,db):
    state=_offer(orm)
    state['confirmation_request']={
        'id':'recap-a','kind':'book','status':'awaiting_confirmation',
        'unit_id':'H-201','date':'2026-11-27','start_time':'10:00',
        'recap_message_id':'reply-a',
    }
    db.get(orm.SalesMessage,'reply-a').content='Confirm visit for H-201 on 2026-11-27 at 10:00?'
    result=orm.store.save(db,SCOPE,expected_revision=0,event_key='valid-recap',state=state)
    db.commit()
    assert result.revision == 1
    saved=orm.store.load(db,SCOPE)
    assert saved.data['confirmation_request']['unit_id']=='H-201'
    assert saved.data['confirmation_request']['recap_message_id']=='reply-a'


def test_visit_menu_rejects_label_that_was_not_visible(orm,db):
    state=_offer(orm)
    state['last_presented_choice_set']={
        'type':'visit_time','source_reply_message_id':'menu-a',
        'options':[{'index':1,'label':'2026-11-27 at 10:00'},
                   {'index':2,'label':'2026-11-27 at 11:00'}],
    }
    with pytest.raises(PermissionError,match='label was not visible'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='hidden-choice',state=state)


def test_slot_offer_rejects_overlarge_option_array(orm,db):
    state=_offer(orm)
    state['last_slot_search']['options']=[{'date':'2026-11-27','start_time':'10:00'}]*81
    with pytest.raises(ValueError,match='invalid'):
        orm.store.save(db,SCOPE,expected_revision=0,event_key='oversized',state=state)


def test_p04_alembic_additive_receipts_table_matches_orm(orm):
    """Exercise both successive migrations against an isolated SQLite schema."""
    from pathlib import Path
    import importlib
    import runpy
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    Model=importlib.import_module('app.modules.hermes_sales_core.bp_operation_models').HermesSalesOperation
    engine=create_engine('sqlite:///:memory:')
    for table in orm.Base.metadata.sorted_tables:
        if not table.name.startswith('hermes_sales_'):
            table.create(engine)
    migrations=Path(__file__).resolve().parents[1]/'alembic'/'versions'
    p03=runpy.run_path(str(migrations/'20261125_hermes_sales_p03.py'))
    p04=runpy.run_path(str(migrations/'20261125_hermes_sales_p04.py'))
    assert p04['down_revision']==p03['revision']
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            p03['upgrade']()
            p04['upgrade']()
        actual={col['name'] for col in inspect(conn).get_columns('hermes_sales_operations')}
        assert actual==set(Model.__table__.columns.keys())
        assert inspect(conn).get_unique_constraints('hermes_sales_operations')
        assert 'hermes_sales_states' in inspect(conn).get_table_names()
    engine.dispose()


def test_type_only_project_can_keep_draft_visit(orm,db):
    state=orm.store.blank_state(SCOPE)
    state['visit_draft']={'unit_id':'type-a','date':None,'start_time':None,'status':'day_needed'}
    saved=orm.store.save(db,SCOPE,expected_revision=0,event_key='type-visit',state=state)
    assert saved.data['visit_draft']['unit_id']=='type-a'
