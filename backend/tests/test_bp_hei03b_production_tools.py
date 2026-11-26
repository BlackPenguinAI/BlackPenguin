"""HEI-03B focused adapter contracts, not a certified live workflow.

Uses the existing HEI-01B SQLite fixture and doubles for native BP business
services. No SDK/model, provider calls, calendar calls or production DB.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
from uuid import uuid4
import importlib.util
import sys

import pytest
from sqlalchemy import Column, JSON, String
from sqlalchemy.orm import declarative_base
from test_bp_hei01b_staged_runtime import unit

NOW=datetime(2026,11,26,12,tzinfo=timezone.utc)
REQUEST={'id':'req-1','kind':'book','unit_id':'type-a','date':'2026-11-27','start_time':'10:00',
         'timezone':'America/Lima','starts_at_utc':'2026-11-27T15:00:00+00:00','visit_address':'123 Main Street'}


@pytest.fixture
def prod(unit,monkeypatch):
    pkg=sys.modules[unit.staged.__package__]
    root=Path(__file__).resolve().parents[1]/'app'/'modules'/'hermes_sales_core'
    def install(name,**attrs):
        m=ModuleType(name);m.__dict__.update(attrs);monkeypatch.setitem(sys.modules,name,m)
        return m
    def load(name):
        spec=importlib.util.spec_from_file_location(pkg.__name__+'.'+name,root/(name+'.py'))
        m=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,m)
        monkeypatch.setattr(pkg,name,m,raising=False);spec.loader.exec_module(m);return m
    mod=load('production_tools')
    return NS(u=unit,m=mod,install=install,load=load,mp=monkeypatch,pkg=pkg)


@pytest.mark.parametrize('name',['execute_first_live_booking','persist_live_preferences','prepare_live_material_batch'])
def test_production_entrypoints_blocked_before_database_access(prod,name):
    with pytest.raises(prod.u.selection.EngineUnavailable):
        getattr(prod.m,name)(None,prod.u.scope,inbound_message_id='x')


def test_receipt_reconciliation_also_requires_ready_engine(prod):
    with pytest.raises(prod.u.selection.EngineUnavailable):
        prod.m.material_delivery_receipt(None,prod.u.scope,message_ids=['msg'],expected_share_ids=['share'],channel='sms')


def meeting(**changes):
    return NS(**{**dict(id='meeting-1',project_id='project-a',lead_id='lead-a',assigned_sales_user_id='advisor-a',
        visit_context={'project_name':'Project A','timezone':'America/Lima','property_type_id':'type-a'},
        is_demo=False,duration_minutes=60,visit_address='123 Main Street',visit_location_label='Showroom',
        meeting_time=datetime(2026,11,27,15)),**changes})


def test_calendar_snapshot_matches_existing_sync_contract(prod):
    row=prod.m.calendar_snapshot(meeting(),REQUEST,NS(id='advisor-a'))
    assert row['option']=={'starts_at':'2026-11-27T15:00:00+00:00','sales_user_id':'advisor-a'}
    assert row['context']['project_name']=='Project A'
    assert row['context']['duration_minutes']==60
    assert row['context']['location']['address']=='123 Main Street'
    assert row['context']['timezone']=='America/Lima'


@pytest.mark.parametrize('changes',[{'is_demo':True},{'duration_minutes':45},{'assigned_sales_user_id':'other'},
    {'visit_address':None},{'meeting_time':datetime(2026,11,27,16)},{'visit_context':{'project_name':'X','timezone':'UTC'}}])
def test_calendar_snapshot_rejects_invalid_meeting(prod,changes):
    with pytest.raises(prod.m.ProductionToolError):prod.m.calendar_snapshot(meeting(**changes),REQUEST,NS(id='advisor-a'))


def catalog(prod, inventory=None):
    data={'inventory_source':'individual_units','property_types':[{'id':'type-a','property_type':'Van Buren','available_units':2}],
          'inventory':inventory if inventory is not None else [{'id':'unit-a','unit_code':'H-201','status':'available','inventory_updated_at':'2026-11-25'}]}
    prod.install('app.modules.sales_agent.commercial_context',build_commercial_context=lambda *a,**k:data)
    return data


def test_approved_type_and_unit_resolve(prod):
    catalog(prod)
    assert prod.m._resolve_property(None,prod.u.scope,None,'type-a','sms')==('type-a',None,'Van Buren')
    assert prod.m._resolve_property(None,prod.u.scope,None,'H-201','sms',require_available=True)==(None,'unit-a','H-201')
    with pytest.raises(prod.m.ProductionToolError):prod.m._resolve_property(None,prod.u.scope,None,'foreign','sms')


def test_sold_unit_not_bookable_but_discoverable(prod):
    catalog(prod,[{'id':'unit-a','unit_code':'H-201','status':'sold','inventory_updated_at':'2026-11-25'}])
    with pytest.raises(prod.m.ProductionToolError):prod.m._resolve_property(None,prod.u.scope,None,'H-201','sms',require_available=True)
    assert prod.m._resolve_property(None,prod.u.scope,None,'H-201','sms')[1]=='unit-a'


def test_duplicate_reference_fails_closed(prod):
    catalog(prod,[{'id':'unit-a','unit_code':'H-201'},{'id':'unit-b','unit_code':'H-201'}])
    with pytest.raises(prod.m.ProductionToolError):prod.m._resolve_property(None,prod.u.scope,None,'H-201','sms')


def _provider_rows(prod, **changes):
    scope=prod.u.scope
    row=NS(id='msg',conversation_id=scope.conversation_id,channel='sms',direction='outbound',role='assistant',
           status='sent',provider_message_id='provider-id',content='Message',metadata_json={'lead_id':scope.lead_id,
           'project_id':scope.project_id,'outbound_message_id':'out'})
    out=NS(id='out',conversation_id=scope.conversation_id,channel='sms',status='sent',
           provider_message_id='provider-id',content='Message',agent_run_id='run')
    for key,value in changes.items():setattr(row,key,value)
    # Keep the fixture's original module object intact.
    mod=sys.modules['app.modules.sales_agent.models'];prod.mp.setattr(mod,'OutboundMessage',object(),raising=False)
    db=NS(get=lambda cls,key:out if key=='out' else None)
    return db,row,out


def test_exact_provider_receipt_required(prod):
    db,row,out=_provider_rows(prod)
    assert prod.m._verify_provider_receipt(db,row,prod.u.scope,'sms') is out
    out.content='Changed message'
    with pytest.raises(prod.m.ProductionToolError):prod.m._verify_provider_receipt(db,row,prod.u.scope,'sms')


@pytest.mark.parametrize('changes',[{'status':'queued'},{'status':'delivery_unknown'},{'provider_message_id':None},
    {'metadata_json':{'lead_id':'another'}},{'channel':'simulation'},{'role':'user'}])
def test_unaccepted_or_foreign_message_rejected(prod,changes):
    db,row,out=_provider_rows(prod,**changes)
    with pytest.raises(prod.m.ProductionToolError):prod.m._verify_provider_receipt(db,row,prod.u.scope,'sms')


@pytest.fixture
def materials(prod):
    scope=prod.u.scope
    catalog(prod)
    class Asset:pass
    rows={key:NS(id=key) for key in ('asset-a','asset-b')}
    flags=NS(approved=list(rows),blocked=None,fail_snapshot=None)
    class Query:
        def filter_by(self,**kw):self.kw=kw;return self
        def populate_existing(self):return self
        def with_for_update(self):return self
        def one_or_none(self):
            assert self.kw['company_id']==scope.company_id and self.kw['project_id']==scope.project_id
            return rows.get(self.kw['id'])
    prod.install('app.modules.projects.models',ProjectSalesAsset=Asset)
    prod.install('app.modules.projects.sales_asset_service',approved_for_turn=lambda *a,**k:[rows[x] for x in flags.approved])
    prod.install('app.modules.projects.asset_coverage',matches=lambda a,**kw:[] if a.id==flags.blocked else [{'coverage':'requested_tag'}])
    def snapshot(a,channel):
        if a.id==flags.fail_snapshot:raise ValueError('missing file')
        return {'asset_id':a.id,'sha256':'hash-'+a.id,'channel':channel}
    prod.install('app.modules.sales_agent.material_delivery',snapshot=snapshot)
    prod.install(prod.pkg.__name__+'.bp_operational_port',_fresh=lambda d,now:datetime.fromisoformat(d['expires_at'])>now)
    draft={'unit_id':'type-a','subject':'brochure','asset_ids':['asset-a','asset-b'],'expires_at':(NOW+timedelta(minutes=10)).isoformat()}
    return NS(p=prod,flags=flags,db=NS(query=lambda model:Query()),draft=draft)


def test_multi_asset_batch_checks_exact_order_and_channel(materials):
    x=materials
    result=x.p.m._material_batch(x.db,x.p.u.scope,None,'whatsapp',x.draft,NOW)
    assert [v['asset_id'] for v in result]==['asset-a','asset-b']
    assert all(v['channel']=='whatsapp' for v in result)
    assert all('url' not in v for v in result)


@pytest.mark.parametrize('change',['unapproved','coverage','file','duplicate','expired','unknown_subject'])
def test_material_batch_fails_as_whole(materials,change):
    x=materials
    if change=='unapproved':x.flags.approved=['asset-a']
    elif change=='coverage':x.flags.blocked='asset-b'
    elif change=='file':x.flags.fail_snapshot='asset-b'
    elif change=='duplicate':x.draft['asset_ids']=['asset-a','asset-a']
    elif change=='expired':x.draft['expires_at']=NOW.isoformat()
    else:x.draft['subject']='unknown'
    with pytest.raises((x.p.m.ProductionToolError,ValueError)):
        x.p.m._material_batch(x.db,x.p.u.scope,None,'whatsapp',x.draft,NOW)


@pytest.fixture
def profiles(prod):
    # Load the real pure parser and commercial scope from the pinned repository.
    prod.load('sales_preferences');prod.load('commercial_turn')
    return prod


@pytest.mark.parametrize('text,group,value,currency,expected',[
    ('My maximum budget is $300,000','budget',{'mode':'cap','maximum_usd':300000},'USD',{'budget_maximum':300000}),
    ('My maximum budget is USD 300000','budget',{'mode':'cap','maximum_usd':300000},'PEN',{'budget_maximum':300000}),
    ('I need exactly 2 bedrooms','bedrooms',{'mode':'exact','preferred':2},'USD',{'bedrooms':2}),
    ('I need at least 3 bedrooms','bedrooms',{'mode':'minimum','minimum':3},'USD',{'bedrooms':'I need at least 3 bedrooms'}),
])
def test_direct_preferences_require_matching_evidence(profiles,text,group,value,currency,expected):
    values=profiles.m.direct_profile_values(text,{group:value},project_currency=currency)
    assert all(values[k]==v for k,v in expected.items())


@pytest.mark.parametrize('text', ['Show me houses under $400,000','My friend said my budget is $400,000',
    'My maximum budget is $400,000 and I pay $500 rent','My maximum budget is $400,000?',
    'My maximum budget is EUR 400000','My maximum budget is $400,000'])
def test_ambiguous_exploratory_or_currency_mismatch_does_not_write(profiles,text):
    assert profiles.m.direct_profile_values(text,{'budget':{'mode':'cap','maximum_usd':400000}},project_currency='PEN')=={}


def test_state_disagreement_rejected(profiles):
    assert profiles.m.direct_profile_values('My maximum budget is $300,000',{'budget':{'mode':'cap','maximum_usd':400000}},project_currency='USD')=={}


def test_native_booking_calls_existing_scheduler_and_persists_calendar_job(prod):
    p=prod;catalog(p)
    jobs=[NS(reason='initial_cadence',status='pending'),NS(reason='manual_followup',status='pending')]
    calls=[];added=[]
    class Query:
        def filter_by(self,**kw):return self
        def filter(self,*a):return self
        def all(self):return jobs
    class Status:
        def in_(self,*a):return True
    class FollowUp:status=Status()
    p.mp.setattr(sys.modules['app.modules.sales_agent.models'],'SalesFollowUpJob',FollowUp,raising=False)
    p.install('app.modules.onboarding_versions',require_capability=lambda *a:None)
    p.install('app.modules.projects.locations',resolve_visit_location=lambda x:{'address':'123 Main Street','label':'Showroom'})
    def schedule(db,**kwargs):
        calls.append(kwargs)
        return meeting(visit_property_type_id='type-a',visit_unit_id=None),NS(id='advisor-a')
    p.install('app.modules.sales_crm.scheduling',create_agent_appointment=schedule)
    p.install('app.modules.sales_agent.first_booking',active_meetings=lambda *a:[])
    p.install('app.modules.sales_agent.booking_models',SalesBookingOperation=lambda **kw:NS(id='booking-1',**kw))
    p.install(p.pkg.__name__+'.bp_effect_executor',_visit_starts=lambda req,now:datetime(2026,11,27,15))
    db=NS(add=added.append,flush=lambda:None,query=lambda model:Query())
    lead=NS(id=p.u.scope.lead_id,next_action_at=NOW);conv=NS(id=p.u.scope.conversation_id,channel='sms')
    result=p.m._book(db,p.u.scope,NS(profile={},timezone='America/Lima'),lead,conv,REQUEST,NOW)
    assert len(calls)==1 and calls[0]['defer_calendar'] is True
    assert calls[0]['duration_minutes']==60 and calls[0]['visit_property_type_id']=='type-a'
    assert result['delivery']=='not_sent' and result['calendar_status']=='pending'
    assert added[0].calendar_status=='pending' and added[0].snapshot_json['option']['sales_user_id']=='advisor-a'
    assert conv.stage=='appointment_confirmed' and lead.next_action_at is None
    assert jobs[0].status=='cancelled' and jobs[1].status=='pending'


def test_native_booking_refuses_existing_active_meeting(prod):
    p=prod
    p.install('app.modules.onboarding_versions',require_capability=lambda *a:None)
    p.install('app.modules.projects.locations',resolve_visit_location=lambda x:None)
    p.install('app.modules.sales_crm.scheduling',create_agent_appointment=lambda *a,**k:pytest.fail('duplicate booking'))
    p.install('app.modules.sales_agent.first_booking',active_meetings=lambda *a:[meeting()])
    p.install('app.modules.sales_agent.booking_models',SalesBookingOperation=object)
    p.mp.setattr(sys.modules['app.modules.sales_agent.models'],'SalesFollowUpJob',object,raising=False)
    p.install(p.pkg.__name__+'.bp_effect_executor',_visit_starts=lambda *a:None)
    with pytest.raises(p.m.ProductionToolError,match='active real appointment'):
        p.m._book(None,p.u.scope,NS(profile={},timezone='America/Lima'),None,None,REQUEST,NOW)


def _crm_fixture(prod, staff=False):
    current={'bedrooms':{'id':'old','field':'bedrooms','value':2,'status':'confirmed' if staff else 'declared',
                         'source':'staff_verified' if staff else 'active_conversation'}}
    lead=NS(lead_profile_data={'optional_profile':{'preserve':True},'facts':{'bedrooms':{'value':2}}})
    def resolve(row):
        stored=row.lead_profile_data.get('sales_profile') or {}
        return {'current':deepcopy(stored.get('current',current)), 'history':deepcopy(stored.get('history',[]))}
    def record(field,value,**kw):return {'id':field+'-'+str(value)+'-'+kw['source_ref']['message_id'],
        'field':field,'value':value,'captured_at':kw.pop('at').isoformat(),**kw}
    mod=prod.install('app.modules.sales_agent.lead_profile',VERSION='sales-lead-profile/2.0',resolve=resolve,record=record)
    # from app.modules.sales_agent import lead_profile must resolve the seam.
    package=sys.modules.get('app.modules.sales_agent')
    if package is None:package=prod.install('app.modules.sales_agent',__path__=[])
    prod.mp.setattr(package,'lead_profile',mod,raising=False)
    prod.install('app.modules.sales_crm.intelligence',lead_profile_summary=lambda x:x)
    return lead,NS(id='inbound',content='I need exactly 3 bedrooms',created_at=NOW),NS(flush=lambda:None)


def test_profile_write_preserves_legacy_fields_and_records_evidence(prod):
    lead,inbound,db=_crm_fixture(prod)
    assert prod.m._write_profile(db,lead,inbound,{'bedrooms':3})==['bedrooms']
    saved=lead.lead_profile_data
    assert saved['optional_profile']=={'preserve':True}
    assert saved['sales_profile']['history'][0]['value']==2
    assert saved['sales_profile']['current']['bedrooms']['source_ref']=={'message_id':'inbound'}
    assert saved['facts']['bedrooms']['confirmed'] is False
    assert prod.m._write_profile(db,lead,inbound,{'bedrooms':3})==[]
    assert len(lead.lead_profile_data['sales_profile']['history'])==1


def test_profile_does_not_replace_staff_verified_field(prod):
    lead,inbound,db=_crm_fixture(prod,staff=True)
    before=deepcopy(lead.lead_profile_data)
    with pytest.raises(prod.m.ProductionToolError,match='staff-verified'):
        prod.m._write_profile(db,lead,inbound,{'bedrooms':3})
    assert lead.lead_profile_data==before


def _delivery_fixture(prod):
    p=prod;scope=p.u.scope
    db,row,out=_provider_rows(p)
    row.content='Brochure: https://example.invalid/api/v1/projects/a/test-only-token'
    out.content=row.content
    row.metadata_json.update(engine='hermes-agent',agent_run_id='run',delivery_group={'key':'group','part':1,'total':1},sales_asset_share_ids=['share'])
    share=NS(id='share',company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id,
        channel='sms',agent_run_id='run',outbound_message_id='out',token_hash=sha256(b'test-only-token').hexdigest())
    class Field:
        def in_(self,*a):return True
    class Share:id=Field()
    class Q:
        def filter(self,*a):return self
        def all(self):return [share]
    p.install('app.modules.projects.models',SalesAssetShare=Share)
    p.install('app.modules.sales_agent.material_delivery',validate_shares=lambda *a,**kw:True)
    p.install('app.modules.sales_agent.conversation_scope',scoped_messages_query=lambda *a: NS(filter_by=lambda **kw:NS(one_or_none=lambda:row)))
    p.install(p.pkg.__name__+'.bp_context',require_scoped_entities=lambda *a:(None,None,None,NS(channel='sms')))
    p.mp.setattr(p.m,'require_selectable',lambda *a:None)
    db.query=lambda *a:Q()
    return db,row,out,share


def test_material_provider_acceptance_not_claimed_as_device_delivery(prod):
    db,row,out,share=_delivery_fixture(prod)
    result=prod.m.material_delivery_receipt(db,prod.u.scope,message_ids=['msg'],expected_share_ids=['share'],channel='sms')
    assert result['status']=='provider_accepted' and 'test-only-token' not in str(result)
    row.status=out.status='delivered'
    assert prod.m.material_delivery_receipt(db,prod.u.scope,message_ids=['msg'],expected_share_ids=['share'],channel='sms')['status']=='delivered'


@pytest.mark.parametrize('change',['outbox','token','group','missing_share'])
def test_material_receipt_rejects_unverified_links(prod,change):
    db,row,out,share=_delivery_fixture(prod)
    if change=='outbox':share.outbound_message_id='other'
    if change=='token':share.token_hash='wrong'
    if change=='group':row.metadata_json['delivery_group']['total']=2
    if change=='missing_share':row.metadata_json['sales_asset_share_ids']=[]
    with pytest.raises(prod.m.ProductionToolError):
        prod.m.material_delivery_receipt(db,prod.u.scope,message_ids=['msg'],expected_share_ids=['share'],channel='sms')
