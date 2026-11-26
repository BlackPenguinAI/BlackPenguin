"""HEI-04 projection/permissions using real models and isolated SQLite.

No SDK/provider calls; no production database. All identities/data synthetic.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.companies.models import Company
from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType, ProjectOnboardingSource, ProjectSalesAsset, SalesAssetShare
from app.modules.sales_crm.models import Lead, Meeting, MeetingStatus
from app.modules.users.models import User, UserRole, UserProjectAccess
from app.modules.sales_agent.models import SalesConversation, SalesConversationLeadContext, SalesMessage, AgentRun, OutboundMessage, SalesInboundJob
from app.modules.hermes_sales_core.bp_models import HermesSalesState, HermesSalesStateEvent
from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
from app.modules.hermes_sales_core.bp_state_store import blank_state
from app.modules.hermes_sales_core.contracts import TurnScope
from app.modules.hermes_sales_core.conversation_inspector import inspect_conversation, scoped_query, verified_run_labels
from app.modules.hermes_sales_core.staff_router import tenant_context, tenant_meeting_context
from app.modules.sales_agent.operational_context import scoped_conversation

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
SCOPE = TurnScope('company','project','conversation','lead')


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([
            Company(id='company',name='Test Company'), Company(id='foreign',name='Foreign'),
            Project(id='project',company_id='company',name='Project',timezone='America/Lima'),
            Project(id='other',company_id='company',name='Other Project'),
            Project(id='foreign-project',company_id='foreign',name='Foreign Project'),
            ProjectProfile(id='profile',project_id='project',final_approved=True),
            ProjectPropertyType(id='van',project_id='project',name='Van Buren',bedrooms=3,starting_price=325000,currency='USD'),
            ProjectPropertyType(id='oak',project_id='project',name='Oakwood',bedrooms=4,starting_price=390000,currency='USD'),
            ProjectPropertyType(id='secret-property',project_id='other',name='Outside Project',bedrooms=4,starting_price=123,currency='USD'),
            User(id='admin',company_id='company',email='admin@example.invalid',hashed_password='test',role=UserRole.ADMIN),
            User(id='sales',company_id='company',email='sales@example.invalid',hashed_password='test',role=UserRole.SALES,first_name='Test',last_name='Advisor'),
            User(id='other-sales',company_id='company',email='other-sales@example.invalid',hashed_password='test',role=UserRole.SALES),
            User(id='mkt',company_id='company',email='mkt@example.invalid',hashed_password='test',role=UserRole.MKT,project_access_scope='selected'),
            User(id='foreign-admin',company_id='foreign',email='foreign@example.invalid',hashed_password='test',role=UserRole.ADMIN),
            Lead(id='lead',company_id='company',project_id='project',full_name='Synthetic Lead',phone='+10000000000',consent_status='granted',assigned_sales_user_id='sales',meta_form_data={'purchase_timeline':'Within 3 months'}),
            Lead(id='old-lead',company_id='company',project_id='other',full_name='Old Lead',phone='+10000000000'),
            SalesConversation(id='conversation',company_id='company',project_id='project',lead_id='lead',channel='sms',is_paused=False,
                continuity_json={'lead_id':'lead','project_id':'project','epoch':2,'sales_engine_boundary':'hermes'}),
        ])
        session.commit()
        yield session
    engine.dispose()


def conv(db): return db.get(SalesConversation,'conversation')


def view(db): return inspect_conversation(db,conv(db))


def inbound(db, mid='inbound', at=None, **meta):
    m=SalesMessage(id=mid,conversation_id='conversation',channel='sms',direction='inbound',role='user',status='received',content='Synthetic budget declaration',created_at=at or NOW-timedelta(minutes=3),metadata_json={'lead_id':'lead','project_id':'project',**meta})
    db.add(m);db.flush();return m


def run(db, mid='inbound', identifier='run', engine='hermes/live/1', **output):
    r=AgentRun(id=identifier,conversation_id='conversation',event_id='event-'+identifier,mode='live',status='completed',graph_version=engine,toolset_version='test',prompt_snapshot={'system_prompt':'SECRET PROMPT'},model='test/model',input_snapshot={'message_id':mid},output_snapshot=output,started_at=NOW-timedelta(minutes=2),completed_at=NOW-timedelta(minutes=1,seconds=30))
    db.add(r);db.flush();return r


def reply(db, identifier='outbound', run_id='run', status='accepted', out_status=None, text='Synthetic reply', **metadata):
    o=OutboundMessage(id='out-'+identifier,conversation_id='conversation',agent_run_id=run_id,idempotency_key='key-'+identifier,channel='sms',content=text,status=out_status or status,provider_message_id='provider-'+identifier)
    m=SalesMessage(id=identifier,conversation_id='conversation',channel='sms',direction='outbound',role='assistant',content=text,status=status,provider_message_id=o.provider_message_id,created_at=NOW-timedelta(minutes=1),metadata_json={'lead_id':'lead','project_id':'project','agent_run_id':run_id,'outbound_message_id':o.id,'engine':'hermes-agent','continuity_epoch':2,**metadata})
    db.add_all([o,m]);db.flush();return m,o


def persisted(db, **overrides):
    data=blank_state(SCOPE);data['conversation_focus']['property_type_id']='van'
    data['search_preferences']={'revision':3,'budget':{'mode':'cap','maximum_usd':350000,'currency':'USD'},'bedrooms':{'mode':'exact','preferred':3},'last_source_message_id':'inbound'}
    data['active_search']={'scope':'temporary','criteria':{'bedrooms':4,'max_price_usd':400000,'unsafe':'secret'},'match_count':2,'source_inbound_message_id':'inbound'}
    data.update(overrides)
    row=HermesSalesState(**SCOPE.__dict__,revision=8,state_json=data,updated_at=NOW)
    db.add(row);db.flush();return row


def test_missing_hermes_state_is_not_an_error_or_activation(db):
    h=view(db)
    assert not h['has_state'] and not h['routing']['hermes_live_ready']
    assert h['routing']['effective_sales_engine']=='langgraph' and h['crm_facts']['purchase_timeline']['value']=='Within 3 months'
    assert h['revision'] is None and h['focus'] is None


def test_primary_vs_temporary_and_source_evidence(db):
    inbound(db);persisted(db);h=view(db)
    assert h['focus']['name']=='Van Buren' and h['focus']['price']==325000
    assert h['primary_preferences']['budget']['maximum_usd']==350000
    assert h['primary_preferences']['bedrooms']['preferred']==3
    assert h['active_search']['criteria']=={'bedrooms':4,'max_price_usd':400000}
    assert h['active_search']['match_count']==2 and h['active_search']['source']['message_id']=='inbound'
    assert h['primary_preferences']['source']['message_id']=='inbound'
    assert h['phase']=='property_exploration' and h['phase_source']=='observed'


def test_foreign_or_unapproved_focus_never_resolves(db):
    persisted(db,conversation_focus={'project_id':'project','property_type_id':'secret-property'})
    h=view(db);assert h['focus'] is None and h['focus_status']=='not_in_approved_catalog'
    assert 'Outside Project' not in json.dumps(h)


def test_ambiguity_does_not_select_an_arbitrary_property(db):
    persisted(db,conversation_focus={'project_id':'project','property_type_id':'van','ambiguous':True})
    h=view(db);assert h['focus'] is None and h['focus_status']=='ambiguous'


def test_booked_property_independent_of_focus_and_calendar_receipt(db):
    persisted(db);db.add(Meeting(id='visit',project_id='project',lead_id='lead',assigned_sales_user_id='sales',meeting_time=NOW+timedelta(days=2),duration_minutes=60,status=MeetingStatus.CONFIRMED,visit_property_type_id='oak',visit_context={'property_type_name':'Oakwood','timezone':'America/Lima'},calendar_sync_status='pending',visit_address='Synthetic address'));db.flush()
    h=view(db);assert h['focus']['name']=='Van Buren'
    assert h['visits'][0]['property_name']=='Oakwood' and h['visits'][0]['status']=='confirmed'
    assert h['visits'][0]['calendar_status']=='pending' and h['visits'][0]['active'] and h['visits'][0]['duration_minutes']==60


def test_run_attribution_does_not_use_global_engine_and_tools_are_allowlisted(db):
    inbound(db);r=run(db,tool_observations=[{'tool':'get_unit_details','status':'executed','arguments':{'api_key':'SENSITIVE'},'result':'private body'},{'tool':'shell','status':'executed'},{'tool':'get_unit_media','status':'rejected','error_code':'NO_ASSET'}]);reply(db);persisted(db)
    h=view(db);events=[e for e in h['timeline'] if e['kind']=='run'];assert len(events)==1 and events[0]['engine']=='hermes'
    assert h['last_engine']=='hermes' and h['routing']['effective_sales_engine']=='langgraph'
    assert [t['tool'] for t in events[0]['tools']]==['get_unit_details','get_unit_media']
    assert events[0]['at'].endswith('+00:00') and events[0]['ended_at']
    assert 'SECRET PROMPT' not in json.dumps(h) and 'private body' not in json.dumps(h) and 'SENSITIVE' not in json.dumps(h)


def test_unbound_assistant_message_not_attributed_to_hermes(db):
    inbound(db);reply(db,run_id=None);h=view(db)
    assert h['last_engine']=='unknown'
    assert verified_run_labels(db,conv(db),scoped_query(db,conv(db)).all())['outbound']=='unknown'


def test_scoped_query_rejects_conflicting_attribution_and_reused_thread(db):
    db.add_all([SalesConversationLeadContext(conversation_id='conversation',lead_id='old-lead',is_active=False,activated_at=NOW-timedelta(days=1)),SalesConversationLeadContext(conversation_id='conversation',lead_id='lead',is_active=True,activated_at=NOW-timedelta(minutes=5))]);db.flush()
    inbound(db,'old',at=NOW-timedelta(days=1),lead_id='old-lead',project_id='other');inbound(db,'conflict',lead_id='old-lead',project_id='other');inbound(db,'good')
    persisted(db);h=view(db);m=[e['message_id'] for e in h['timeline'] if e['kind']=='message']
    assert m==['good'] and h['primary_preferences']['source'] is None


def test_previous_activation_state_is_not_current(db):
    db.add(SalesConversationLeadContext(conversation_id='conversation',lead_id='lead',is_active=True,activated_at=NOW+timedelta(seconds=1)));db.flush();persisted(db)
    h=view(db);assert h['historical_state'] and not h['has_state'] and h['focus'] is None


def test_deleted_and_foreign_users_rejected(db):
    assert tenant_context('conversation',db,db.get(User,'admin'))['scope']['lead_id']=='lead'
    for actor in ('foreign-admin','other-sales','mkt'):
        with pytest.raises(HTTPException) as ex:tenant_context('conversation',db,db.get(User,actor))
        assert ex.value.status_code==404
    lead=db.get(Lead,'lead');lead.deleted_at=NOW;db.flush()
    with pytest.raises(HTTPException) as ex:tenant_context('conversation',db,db.get(User,'admin'))
    assert ex.value.status_code==404


def test_sales_and_marketing_project_access(db):
    assert tenant_context('conversation',db,db.get(User,'sales'))['read_only']
    db.add(UserProjectAccess(user_id='mkt',project_id='project',is_active=True));db.flush()
    assert tenant_context('conversation',db,db.get(User,'mkt'))['scope']['project_id']=='project'


def test_restricted_meeting_never_projects_conversation(db, monkeypatch):
    # The existing Schedule policy may grant the meeting but restrict its
    # lead's conversation. No second full-state read is allowed.
    from app.modules.sales_agent import operational_context
    monkeypatch.setattr(operational_context,'meeting_context',lambda *_:{'scope_limited':True,'appointments':[]})
    result=tenant_meeting_context('visit',db,db.get(User,'other-sales'))
    assert result['scope_limited'] and not result['has_state'] and 'state' not in result


def test_stale_visit_proposal_after_engine_change(db):
    inbound(db);run(db);reply(db,text='Confirm van on 2026-12-02 at 10:00 (America/Lima), Synthetic address?')
    persisted(db,confirmation_request={'kind':'book','status':'awaiting_confirmation','unit_id':'van','date':'2026-12-02','start_time':'10:00','timezone':'America/Lima','visit_address':'Synthetic address','expires_at':(NOW+timedelta(minutes=30)).isoformat(),'recap_message_id':'outbound'})
    assert view(db)['confirmation']['status']=='awaiting_confirmation'
    c=conv(db);c.continuity_json={**c.continuity_json,'sales_engine_boundary':'langgraph','epoch':3};db.flush()
    h=view(db);assert h['historical_state'] and h['confirmation']['status']=='stale'


def test_expired_or_unverified_slots_never_shown_as_live_availability(db):
    inbound(db);run(db);reply(db)
    persisted(db,last_slot_search={'unit_id':'van','timezone':'America/Lima','expires_at':(NOW-timedelta(minutes=1)).isoformat(),'source_reply_message_id':'outbound','options':[{'date':'2026-12-02','start_time':'10:00'}]})
    h=view(db);assert h['slot_offer']['status']=='stale_or_unverified' and h['slot_offer']['slots']==[]


def test_material_receipt_requires_exact_provider_and_token_binding(db):
    inbound(db);run(db);persisted(db)
    token='synthetic-bearer-token';body='https://example.invalid/api/v1/projects/a/'+token
    message,out=reply(db,text=body,sales_asset_share_ids=['share'],status='queued')
    db.add_all([ProjectOnboardingSource(id='source',project_id='project',name='Test source',kind='UPLOADED_FILE'),
                ProjectSalesAsset(id='asset',company_id='company',project_id='project',source_id='source',display_name='Van Buren Brochure',asset_type='brochure',content_tags=['brochure']),
                SalesAssetShare(id='share',company_id='company',project_id='project',lead_id='lead',source_id='source',sales_asset_id='asset',outbound_message_id=out.id,agent_run_id='run',channel='sms',token_hash=sha256(token.encode()).hexdigest(),expires_at=NOW+timedelta(days=1),target_url='https://private.example.invalid')]);db.flush()
    assert view(db)['materials'][0]['status']=='queued'
    out.status='delivered';db.flush();assert view(db)['materials'][0]['status']=='unknown'
    message.status='accepted';db.flush();assert view(db)['materials'][0]['status']=='provider_accepted'
    message.status='delivered';db.flush();h=view(db);assert h['materials'][0]['status']=='delivered'
    assert token not in json.dumps(h) and 'private.example' not in json.dumps(h)
    out.content='Different body';db.flush();assert view(db)['materials'][0]['status']=='unknown'


def test_issued_access_without_outbox_is_not_sent(db):
    inbound(db);run(db);persisted(db)
    db.add_all([ProjectOnboardingSource(id='source',project_id='project',name='Test source',kind='UPLOADED_FILE'),ProjectSalesAsset(id='asset',company_id='company',project_id='project',source_id='source',display_name='Plan',asset_type='floor_plan',content_tags=['floor_plan']),SalesAssetShare(id='share',company_id='company',project_id='project',lead_id='lead',source_id='source',sales_asset_id='asset',agent_run_id='run',channel='sms',token_hash='a'*64,expires_at=NOW+timedelta(days=1))]);db.flush()
    assert view(db)['materials'][0]['status']=='issued_not_sent'


def test_operations_and_review_status_are_bounded_and_redacted(db):
    inbound(db);run(db);persisted(db)
    db.add_all([HermesSalesStateEvent(**SCOPE.__dict__,revision=8,event_key='state',event_type='state_update',schema_version='test',payload_hash='a'*64,state_after={'password':'DO_NOT_SHOW'}),HermesSalesOperation(**SCOPE.__dict__,inbound_message_id='inbound',request_id='request',operation_type='material',request_hash='b'*64,status='pending_delivery',result_json={'status':'issued_not_sent','url':'https://secret.example.invalid'}),SalesInboundJob(conversation_id='conversation',message_id='inbound',status='review',error_code='HERMES_RECONCILIATION_REQUIRED',error_message='SECRET DETAILS')]);db.flush()
    h=view(db);assert h['operations'][0]['status']=='pending_delivery';assert any(e['kind']=='job' and e['status']=='review' for e in h['timeline'])
    assert any(e['kind']=='state' and e['revision']==8 for e in h['timeline']);assert 'DO_NOT_SHOW' not in json.dumps(h) and 'SECRET DETAILS' not in json.dumps(h) and 'secret.example' not in json.dumps(h)


def test_projection_does_not_change_state_or_commit(db):
    inbound(db);persisted(db);db.commit();before=db.query(HermesSalesState).one().state_json
    view(db);assert not db.new and not db.dirty and not db.deleted
    assert db.query(HermesSalesState).one().state_json==before


def test_message_endpoint_preserves_text_and_verified_engine_scope(db):
    from app.modules.sales_agent.router import messages
    inbound(db);run(db);reply(db,text='1. Van Buren\n2. Oakwood')
    rows=messages('conversation',db,db.get(User,'admin'))
    assert rows[-1]['content']=='1. Van Buren\n2. Oakwood'
    assert rows[-1]['metadata_json']['inspector_engine']=='hermes'
    assert rows[-1]['metadata_json']['inspector_scope']=={'lead_id':'lead','project_id':'project'}
    db.get(OutboundMessage,'out-outbound').content='wrong';db.flush()
    assert messages('conversation',db,db.get(User,'admin'))[-1]['metadata_json']['inspector_engine']=='unknown'


def test_operational_endpoint_integrates_both_contexts(db,monkeypatch):
    from app.modules.sales_agent.router import operational_context
    from app.modules.sales_agent import operational_context as original
    from app.modules.hermes_sales_core import conversation_inspector
    inbound(db);persisted(db)
    monkeypatch.setattr(original,'snapshot',lambda *a,**kw:{'current_interest':{'property':'Legacy selection'},'scope_limited':False})
    response=Response();result=operational_context('conversation',response,db,db.get(User,'admin'))
    assert response.headers['cache-control']=='no-store'
    assert result['current_interest']['property']=='Legacy selection' and result['hermes_inspector']['focus']['name']=='Van Buren'
    assert result['inspector_scope']['lead_id']=='lead'
    def failed(*args):raise RuntimeError('PRIVATE diagnostic')
    monkeypatch.setattr(conversation_inspector,'inspect_conversation',failed)
    fallback=operational_context('conversation',Response(),db,db.get(User,'admin'))
    assert fallback['current_interest']['property']=='Legacy selection' and fallback['hermes_inspector_error']=='HERMES_INSPECTOR_UNAVAILABLE'
    assert 'PRIVATE diagnostic' not in json.dumps(fallback)
