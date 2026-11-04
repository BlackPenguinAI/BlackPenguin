"""Shared catalogue contract and server-owned quantity confirmation."""
from datetime import datetime
from pathlib import Path
import importlib.util
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_onboarding_revisions_and_money import context
from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user
from app.modules.projects import catalog_service, services
from app.modules.projects.router import router
from app.modules.projects.schemas import PropertyTypeCreate
from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType
from app.modules.projects.completion import FIELD_BY_KEY
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.users.models import User, UserRole


@pytest.fixture
def api(context):
    db,company,user,project,profile,item=context
    app=FastAPI();app.include_router(router,prefix='/projects')
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:user
    with TestClient(app) as client:
        yield client,context


@pytest.mark.parametrize('quantity',[None,0,7])
def test_api_confirms_quantity_with_server_clock_and_authenticated_actor(api,quantity):
    client,(db,company,user,project,profile,item)=api
    before=datetime.utcnow()
    r=client.post(f'/projects/{project.id}/property-types',json={'name':'New type','available_units':quantity,'inventory_updated_at':'2001-01-01T00:00:00Z','inventory_confirmed_by_user_id':'forged'})
    assert r.status_code==201,r.text
    saved=db.get(ProjectPropertyType,r.json()['id'])
    assert saved.available_units==quantity
    if quantity is None:
        assert saved.inventory_updated_at is None
        assert r.json()['inventory_confirmed_by_user_id'] is None
    else:
        assert before<=saved.inventory_updated_at<=datetime.utcnow()
        assert r.json()['inventory_confirmed_by_user_id']==user.id
    assert not profile.final_approved
    # New draft data must never leak into the already-approved revision.
    assert len(build_commercial_context(db,project=project,company_id=company.id,lead_id='test')['property_types'])==1


def test_candidate_is_not_verified_until_user_confirms_it(api):
    client,(db,company,user,project,profile,item)=api
    r=client.post(f'/projects/{project.id}/property-types',json={'name':'Extracted type','available_units':4,'review_status':'candidate'})
    assert r.status_code==201
    assert r.json()['inventory_updated_at'] is None
    r=client.put(f'/projects/{project.id}/property-types/{r.json()["id"]}',json={'name':'Extracted type','available_units':4})
    assert r.status_code==200
    assert r.json()['inventory_updated_at'] and r.json()['inventory_confirmed_by_user_id']==user.id


def test_clearing_quantity_clears_confirmation_without_turning_unknown_into_zero(api):
    client,(db,company,user,project,profile,item)=api
    r=client.put(f'/projects/{project.id}/property-types/{item.id}',json={'name':item.name,'available_units':None})
    assert r.status_code==200
    assert r.json()['available_units'] is None
    assert r.json()['inventory_updated_at'] is None
    assert r.json()['inventory_confirmed_by_user_id'] is None


def test_agent_uses_new_confirmation_only_after_profile_approval(context):
    db,company,user,project,profile,item=context
    catalog_service.update(db,project,item,{'available_units':0},user_id=user.id)
    old=build_commercial_context(db,project=project,company_id=company.id,lead_id='test')
    assert old['property_types'][0]['available_units']==3
    services.complete_onboarding(db,project,user.id)
    new=build_commercial_context(db,project=project,company_id=company.id,lead_id='test')
    assert new['property_types'][0]['available_units']==0
    assert new['property_types'][0]['inventory_updated_at']
    assert new['property_types'][0]['inventory_confirmed_by_user_id']==user.id


def test_description_and_image_only_changes_do_not_reverify_quantity(api):
    client,(db,company,user,project,profile,item)=api
    original=item.inventory_updated_at
    catalog_service.update(db,project,item,{'description':'Reviewed description'},user_id=user.id)
    assert item.inventory_updated_at==original
    assert item.inventory_confirmed_by_user_id is None
    r=client.post(f'/projects/{project.id}/property-types/{item.id}/defer-images')
    assert r.status_code==200
    assert db.get(ProjectPropertyType,item.id).inventory_updated_at==original


def test_unknown_typology_quantity_does_not_publish_a_partial_total_as_complete(context):
    db,company,user,project,profile,item=context
    catalog_service.create(db,project,{'name':'Unknown inventory','review_status':'confirmed','available_units':None},user_id=user.id)
    assert profile.profile_data['available_inventory'] is None


def test_missing_legacy_timestamp_is_not_backfilled_on_read_or_catalog_confirmation(context):
    db,company,user,project,profile,item=context
    item.inventory_updated_at=None;db.commit()
    catalog_service.catalog(db,project)
    catalog_service.confirm_catalog(db,project)
    assert item.inventory_updated_at is None
    assert item.inventory_confirmed_by_user_id is None
    assert 'inventory_updated_at' not in FIELD_BY_KEY


def test_old_published_snapshots_without_new_actor_column_remain_readable(context):
    db,company,user,project,profile,item=context
    snapshot=dict(profile.published_snapshot)
    snapshot['property_types']=[{k:v for k,v in row.items() if k!='inventory_confirmed_by_user_id'} for row in snapshot['property_types']]
    profile.published_snapshot=snapshot;db.commit()
    result=build_commercial_context(db,project=project,company_id=company.id,lead_id='test')
    assert result['property_types'][0]['inventory_confirmed_by_user_id'] is None


@pytest.mark.parametrize('field',['bedrooms','bathrooms','area_min','area_max','total_units','available_units'])
@pytest.mark.parametrize('value',[True,float('inf'),-1])
def test_schema_rejects_invalid_numeric_catalog_values(field,value):
    with pytest.raises(ValidationError):PropertyTypeCreate(name='Type',**{field:value})


@pytest.mark.parametrize('field',['area_max','available_units','maximum_price','currency'])
def test_api_returns_helpful_validation_and_rolls_back_invalid_edits(api,field):
    client,(db,company,user,project,profile,item)=api
    values={'name':item.name,'area_min':20,'area_max':30,'area_unit':'m²','available_units':2,'total_units':3,'starting_price':30,'maximum_price':40,'currency':'USD'}
    values[field]={'area_max':10,'available_units':4,'maximum_price':20,'currency':None}[field]
    r=client.put(f'/projects/{project.id}/property-types/{item.id}',json=values)
    assert r.status_code==422
    assert r.json()['detail']
    db.refresh(item)
    assert item.starting_price==30 and item.available_units==3


def test_catalog_editor_cannot_write_other_company_or_as_sales(api):
    client,(db,company,user,project,profile,item)=api
    from app.modules.companies.models import Company
    foreign=Company(name='Other');db.add(foreign);db.flush()
    other=Project(company_id=foreign.id,name='Foreign');db.add(other);db.commit()
    assert client.post(f'/projects/{other.id}/property-types',json={'name':'Forbidden','available_units':5}).status_code==404
    user.role=UserRole.SALES;db.commit()
    assert client.post(f'/projects/{project.id}/property-types',json={'name':'Forbidden'}).status_code==403


def migration_module():
    filename=Path(__file__).resolve().parents[1]/'alembic/versions/20261104_inventory_confirmation.py'
    spec=importlib.util.spec_from_file_location('catalog_confirmation_migration',filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_inventory_migration_preserves_legacy_data_and_reverses_without_backfill():
    module=migration_module()
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE project_property_types (id VARCHAR(36) PRIMARY KEY, available_units INTEGER, inventory_updated_at DATETIME)')
        connection.exec_driver_sql("INSERT INTO project_property_types VALUES ('legacy', 0, NULL)")
        with Operations.context(MigrationContext.configure(connection)):module.upgrade()
        row=connection.execute(text('SELECT available_units, inventory_updated_at, inventory_confirmed_by_user_id FROM project_property_types')).one()
        assert tuple(row)==(0,None,None)
        with Operations.context(MigrationContext.configure(connection)):module.downgrade()
        assert tuple(connection.exec_driver_sql('SELECT * FROM project_property_types').one())==('legacy',0,None)
    root=Path(__file__).resolve().parents[1]
    cfg=Config(str(root/'alembic.ini'));cfg.set_main_option('script_location',str(root/'alembic'))
    assert ScriptDirectory.from_config(cfg).get_heads()==[module.revision]


def test_inventory_migration_produces_postgresql_ddl_without_data_updates():
    output=io.StringIO()
    context=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
    with Operations.context(context):migration_module().upgrade()
    sql=output.getvalue()
    assert 'ADD COLUMN inventory_confirmed_by_user_id' in sql
    assert 'FOREIGN KEY' in sql and 'ON DELETE SET NULL' in sql
    assert 'UPDATE ' not in sql


@pytest.mark.parametrize('origin,values',[
    ('url',{'name':'Courtyard loft','bedrooms':1,'bathrooms':1.5,'area_min':72,'area_unit':'m²','available_units':0}),
    ('pdf-layout-a',{'name':'Villa B','code':'V-B','description':'Two levels','bedrooms':3,'area_max':180,'area_unit':'m²','features':['Garden']}),
    ('pdf-layout-b',{'name':'Studio 17','bedrooms':0,'bathrooms':1,'starting_price':50,'maximum_price':75,'currency':'EUR','available_units':9}),
])
def test_source_origins_produce_same_candidates_without_invented_values_or_confirmation(context,origin,values):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock,patch
    from app.modules.projects.source_service import _extract_proposals
    from app.modules.projects.models import ProjectOnboardingSource,ProjectSourceKind,ProjectSourceStatus
    db,company,user,project,profile,item=context
    source=ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.URL if origin=='url' else ProjectSourceKind.UPLOADED_FILE,status=ProjectSourceStatus.READY,name=origin,mime_type='text/html' if origin=='url' else 'application/pdf',uploaded_by_user_id=user.id)
    db.add(source);db.flush()
    output=json.dumps({'property_types':[{**values,'inventory_updated_at':'2001-01-01'}],'proposals':[]})
    with patch('app.modules.projects.source_service.get_ai_config',return_value=SimpleNamespace(openrouter_api_key='mock-only',agent_onboarding_proyectos={})),patch('app.modules.projects.source_service.generate_llm_response',AsyncMock(return_value=output)):
        asyncio.run(_extract_proposals(db,source,'Source-specific content',None))
    db.flush()
    candidate=db.query(ProjectPropertyType).filter_by(project_id=project.id,review_status='candidate').one()
    assert candidate.inventory_updated_at is None and candidate.inventory_confirmed_by_user_id is None
    serialized=catalog_service.serialize(candidate)
    for key in ['bedrooms','bathrooms','area_min','area_max','available_units','starting_price','currency']:
        assert serialized[key]==values.get(key)
    catalog_service.update(db,project,candidate,{'review_status':'confirmed'},user_id=user.id)
    assert bool(candidate.inventory_updated_at)==(values.get('available_units') is not None)


@pytest.mark.parametrize('value',[True,False,'12',float('nan'),float('inf'),-3])
def test_extraction_never_turns_invalid_numbers_into_counts_or_prices(value):
    from app.modules.projects.source_service import _catalog_number
    assert _catalog_number(value) is None
    assert _catalog_number(value,integer=True) is None


def test_old_pending_date_question_is_retired_without_erasing_chat_history(api):
    from app.modules.projects.models import ProjectMessage,SenderType
    client,(db,company,user,project,profile,item)=api
    old=services.save_message(db,project.session.id,SenderType.AI,'Original question asking for the inventory date',ui_payload={'field':'inventory_updated_at','label':'Inventory last updated','prompt':'Original question asking for the inventory date','input_type':'text'})
    response=client.get(f'/projects/{project.id}/chat/state')
    assert response.status_code==200,response.text
    db.refresh(old)
    assert old.content=='Original question asking for the inventory date'
    assert old.response_payload['status']=='superseded'
    assert any(m['id']==old.id and m['content']==old.content for m in response.json()['messages'])
    assert response.json()['next_question'].get('field')!='inventory_updated_at'
