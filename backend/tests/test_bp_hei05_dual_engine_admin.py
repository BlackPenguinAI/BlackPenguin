"""HEI-05 selector API contract; existing ORM registry + isolated SQLite.
Identity is the HEI-01A fixture double, never real production authentication.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_bp_hei01a_engine_selection import unit, publish, set_stored


@pytest.fixture
def client(unit):
    app = FastAPI()
    app.include_router(unit.api.router, prefix='/ai')
    with TestClient(app) as c:
        yield c


PATH = '/ai/hermes/engine'
HEADERS = {'x-test-role':'superadmin'}


def read(client):
    r = client.get(PATH, headers=HEADERS)
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-store'
    return r.json()


def select(client, snapshot, engine, note='reviewed'):
    return client.put(PATH, headers=HEADERS, json={
        'active_sales_engine':engine, 'change_note':note,
        'expected_revision':snapshot['revision'],
        'expected_published_version_id':snapshot['published_version_id']})


def test_status_on_empty_registry(unit, client):
    data = read(client)
    assert data['active_sales_engine'] == data['effective_sales_engine'] == 'langgraph'
    assert data['target_default_engine'] == 'hermes'
    assert not data['hermes_live_ready'] and not data['hermes_policy_published']
    assert not data['hermes_policy_enabled'] and not data['hermes_policy_valid']
    assert data['selectable_engines'] == ['langgraph'] and data['revision']==0
    assert 'configuration' not in data and 'system_prompt' not in data
    with unit.factory() as db:
        assert db.get(unit.models.HermesGlobalSettings,'global') is None


def test_enabled_policy_does_not_activate(unit, client):
    with unit.factory() as db:
        version = publish(unit,db,enabled=True)
    data = read(client)
    assert data['published_version_id']==version and data['published_policy_version']==1
    assert data['hermes_policy_published'] and data['hermes_policy_enabled'] and data['hermes_policy_valid']
    assert data['selectable_engines']==['langgraph'] and data['effective_sales_engine']=='langgraph'
    assert data['hermes_policy_model']=='openai/gpt-4o-mini'
    r=select(client,data,'hermes')
    assert r.status_code==409 and r.json()['detail']['code']=='HERMES_NOT_READY'
    assert read(client)==data


def test_policy_valid_but_disabled(unit, client, monkeypatch):
    # Future-gate double; never alters the shipped readiness implementation.
    monkeypatch.setattr(unit.selection,'live_hermes_ready',lambda:True)
    with unit.factory() as db: publish(unit,db,enabled=False)
    data=read(client)
    assert data['hermes_live_ready'] and data['hermes_policy_valid']
    assert not data['hermes_policy_enabled'] and data['selectable_engines']==['langgraph']
    assert select(client,data,'hermes').status_code==409


def test_stale_revision_after_draft(unit, client):
    with unit.factory() as db:
        publish(unit,db,enabled=True);set_stored(unit,db,'hermes')
    data=read(client)
    with unit.factory() as db:
        unit.control.create_draft(db,configuration=unit.control.baseline(),note='another editor',actor_id='staff-a')
    r=select(client,data,'langgraph')
    assert r.status_code==409 and r.json()['detail']['code']=='ENGINE_SELECTION_STALE'
    assert read(client)['active_sales_engine']=='hermes'
    with unit.factory() as db: assert unit.control.versions(db)['total']==2


def test_stale_publication_even_if_revision_same(unit, client):
    with unit.factory() as db:
        publish(unit,db,enabled=True);set_stored(unit,db,'hermes')
        draft=unit.control.create_draft(db,configuration=unit.control.baseline(),note='draft',actor_id='staff-a')
    previous=read(client)
    with unit.factory() as db: unit.control.publish(db,version_id=draft['id'],actor_id='staff-a')
    current=read(client)
    assert previous['revision']==current['revision'] and previous['published_version_id']!=current['published_version_id']
    r=select(client,previous,'langgraph')
    assert r.status_code==409 and r.json()['detail']['code']=='ENGINE_SELECTION_STALE'
    assert read(client)['active_sales_engine']=='hermes'


def test_explicit_repair_preserves_policy_and_creates_audit(unit, client):
    with unit.factory() as db:
        publish(unit,db,enabled=True,iterations=5);set_stored(unit,db,'invalid')
        before=unit.control.snapshot(db)['configuration']
    previous=read(client)
    assert previous['effective_sales_engine'] is None and previous['error_code']=='INVALID_ENGINE_SELECTION'
    r=select(client,previous,'langgraph',note='repair routing')
    assert r.status_code==200
    after=r.json()
    assert after['active_sales_engine']==after['effective_sales_engine']=='langgraph'
    assert after['revision']==previous['revision']+1
    assert after['hermes_policy_enabled'] and after['hermes_policy_valid']
    with unit.factory() as db:
        assert unit.control.snapshot(db)['configuration']==before
        version=unit.control.find_version(db,after['published_version_id'])
        assert version.created_by_user_id=='staff-a' and 'repair routing' in version.change_note
    assert select(client,previous,'langgraph').status_code==409


def test_future_gate_switch_does_not_let_restore_switch_route(unit, client, monkeypatch):
    monkeypatch.setattr(unit.selection,'live_hermes_ready',lambda:True)
    with unit.factory() as db: old=publish(unit,db,enabled=True,iterations=6)
    data=read(client)
    assert data['selectable_engines']==['langgraph','hermes']
    r=select(client,data,'hermes')
    assert r.status_code==200 and r.json()['effective_sales_engine']=='hermes'
    switched=r.json()
    assert switched['published_version_id']!=old
    with unit.factory() as db:
        before=unit.control.snapshot(db)['configuration']
        unit.control.restore(db,version_id=old,actor_id='staff-a')
        assert unit.control.snapshot(db)['configuration']==before
    assert read(client)['active_sales_engine']=='hermes'


def test_mismatched_registry_cannot_be_selected(unit, client, monkeypatch):
    monkeypatch.setattr(unit.selection,'live_hermes_ready',lambda:True)
    with unit.factory() as db:
        publish(unit,db,enabled=True)
        row=db.get(unit.models.HermesGlobalSettings,'global')
        row.configuration={**row.configuration,'max_iterations':3};db.commit()
    data=read(client)
    assert data['hermes_policy_published'] and not data['hermes_policy_valid']
    assert data['selectable_engines']==['langgraph']
    assert select(client,data,'hermes').status_code==409


@pytest.mark.parametrize('role',['admin','assistant','sales','mkt',''])
def test_no_tenant_selector_access(client,role):
    h={'x-test-role':role}
    assert client.get(PATH,headers=h).status_code==403
    assert client.put(PATH,headers=h,json={'active_sales_engine':'langgraph','change_note':'x','expected_revision':0,'expected_published_version_id':None}).status_code==403


def test_malformed_snapshot_and_scope_override(client):
    for extra in ({'expected_revision':-1},{'expected_revision':True},{'expected_revision':'0'},{'company_id':'foreign'}):
        r=client.put(PATH,headers=HEADERS,json={'active_sales_engine':'langgraph','change_note':'x',**extra})
        assert r.status_code==422
