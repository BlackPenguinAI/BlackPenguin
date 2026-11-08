"""Disposable SQLite catalog loader and the real inbound/dispatcher test boundary."""
import asyncio
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import json
import socket
import uuid

from .adapters import FakeCalendar, RecordingMessenger, ScriptedModel
from .clock import FrozenClock

FIXTURES = Path(__file__).resolve().parents[1]/'fixtures'/'sales_ai'


def naive(value):
    if isinstance(value,str):
        value = datetime.fromisoformat(value.replace('Z','+00:00'))
    if value is not None and value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def load_catalog(name='real_catalog_20261108.json'):
    value = json.loads((FIXTURES/name).read_text())
    if value.get('version') != 'sales-ai-catalog/1.0' or value.get('mode') != 'OFFLINE_FIXTURE_ONLY':
        raise ValueError('Only identified offline catalog fixtures may be seeded.')
    return value


class Sandbox:
    def __init__(self, catalog):
        import app.db.base  # Register schema, without init_db/migrations/default writes.
        from app.db.postgres import Base
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        self.catalog = deepcopy(catalog)
        self.clock = FrozenClock(catalog['captured_at'])
        self.engine = create_engine('sqlite:///:memory:')  # Never settings.DATABASE_URL.
        @event.listens_for(self.engine,'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine,autoflush=False,expire_on_commit=False)()
        self.seed()

    def seed(self):
        from app.modules.companies.models import Company
        from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType, ProjectUnit, ProjectOnboardingSource, ProjectSourceKind, ProjectSourceStatus, ProjectSalesAsset
        from app.modules.project_team.models import ProjectUserAssignment
        from app.modules.sales_crm.models import SalesAvailabilityWindow, SalesAvailabilityBlock
        from app.modules.users.models import User, UserRole, UserAuthStatus
        for cid in sorted({p['project']['company_id'] for p in self.catalog['projects']}):
            self.db.add(Company(id=cid,name='Offline Fixture Company '+cid[:8],created_at=self.clock.utcnow()))
        self.db.flush()
        for row in self.catalog.get('specialists',[]):
            self.db.add(User(id=row['id'],company_id=row['company_id'],first_name='Synthetic',last_name='Specialist',
                             email=row['id']+'@example.invalid',hashed_password='OFFLINE_NOT_A_PASSWORD',
                             role=UserRole(str(row['role']).lower()),auth_status=UserAuthStatus(str(row.get('auth_status') or 'active').lower()),
                             is_active=bool(row.get('is_active')),timezone=row.get('timezone') or 'UTC',deleted_at=naive(row.get('deleted_at'))))
        self.db.flush()
        for entry in self.catalog['projects']:
            project = Project(**entry['project'],created_at=self.clock.utcnow())
            self.db.add(project);self.db.flush()
            approval = entry['approval']
            data = deepcopy(entry['facts'])
            if approval.get('sales_authorization_withdrawn'):
                data['sales_authorization'] = False
            profile = ProjectProfile(id=approval['profile_id'],project_id=project.id,profile_data=data,
                                     field_states=deepcopy(entry['field_states']),final_approved=True,
                                     updated_at=naive(approval.get('profile_updated_at')) or self.clock.utcnow())
            self.db.add(profile)
            for row in entry['property_types']:
                attrs = deepcopy(row)
                for key in ('inventory_updated_at','created_at','updated_at'):
                    attrs[key] = naive(attrs.get(key))
                attrs['created_at'] = attrs['created_at'] or self.clock.utcnow()
                attrs['updated_at'] = attrs['updated_at'] or self.clock.utcnow()
                attrs['sort_order'] = attrs.get('sort_order') or 0
                self.db.add(ProjectPropertyType(**attrs))
            for row in entry['units']:
                attrs = deepcopy(row)
                for key in ('inventory_updated_at','created_at','updated_at'):
                    attrs[key] = naive(attrs.get(key))
                attrs['created_at'] = attrs['created_at'] or self.clock.utcnow()
                attrs['updated_at'] = attrs['updated_at'] or self.clock.utcnow()
                self.db.add(ProjectUnit(**attrs))
            if approval['source']=='published_snapshot':
                profile.published_snapshot={'profile_id':profile.id,'company_id':project.company_id,'project_id':project.id,
                                            'revision':approval['revision'],'data':deepcopy(entry['facts']),
                                            'states':deepcopy(entry['field_states']),'sources':{},
                                            'property_types':deepcopy(entry['property_types']),'units':deepcopy(entry['units'])}
            self.db.flush()
            for asset in entry['materials']:
                source=asset.get('source')
                if not source:
                    continue
                if self.db.get(ProjectOnboardingSource,source['id']) is None:
                    self.db.add(ProjectOnboardingSource(id=source['id'],project_id=project.id,
                        kind=ProjectSourceKind.URL,status=ProjectSourceStatus(str(source.get('status') or 'READY').lower()),
                        name='SYNTHETIC placeholder for exported metadata',mime_type=source.get('mime_type'),
                        extracted_links=[{'url':'https://example.invalid/offline/'+source['id'],'kind':'external_reference'}],
                        created_at=self.clock.utcnow(),updated_at=self.clock.utcnow()))
                    self.db.flush()
                attrs={k:deepcopy(v) for k,v in asset.items() if k not in {'source','content_verified','resource_in_sandbox'}}
                for key in ('valid_from','valid_until','approved_at','created_at','updated_at'):
                    attrs[key]=naive(attrs.get(key))
                attrs['created_at']=attrs['created_at'] or self.clock.utcnow()
                attrs['updated_at']=attrs['updated_at'] or self.clock.utcnow()
                self.db.add(ProjectSalesAsset(**attrs))
        self.db.flush()
        for row in self.catalog.get('assignments',[]):
            attrs=deepcopy(row)
            for key in ('created_at','updated_at'):
                attrs[key]=naive(attrs.get(key)) or self.clock.utcnow()
            self.db.add(ProjectUserAssignment(**attrs))
        for table, model in [('weekly_availability',SalesAvailabilityWindow),('dated_availability',SalesAvailabilityBlock)]:
            for row in self.catalog.get(table,[]):
                attrs=deepcopy(row)
                for key in ('starts_at','ends_at'):
                    if key in attrs:attrs[key]=naive(attrs[key])
                self.db.add(model(**attrs))
        self.db.commit()

    def conversation(self, project_id, channel):
        from app.modules.sales_crm.models import Lead
        from app.modules.sales_agent.models import SalesConversation
        from app.modules.projects.models import Project
        project=self.db.get(Project,project_id)
        key=lambda kind:str(uuid.uuid5(uuid.NAMESPACE_URL,'offline-group-a:'+kind+':'+project_id+':'+channel))
        lead=Lead(id=key('lead'),company_id=project.company_id,project_id=project.id,full_name='SYNTHETIC Test Lead',
                  phone='+12025550199',email='lead@example.invalid',is_test=True,is_demo=False,
                  consent_status='granted',agent_status='active',platform='manual',created_at=self.clock.utcnow())
        self.db.add(lead);self.db.flush()
        conversation=SalesConversation(id=key('conversation'),company_id=project.company_id,project_id=project.id,
                  lead_id=lead.id,provider='telnyx',provider_thread_key='offline:'+key('thread'),channel=channel,
                  automation_level=2,is_paused=False,created_at=self.clock.utcnow(),updated_at=self.clock.utcnow())
        self.db.add(conversation);self.db.commit()
        return project,lead,conversation

    def close(self):
        self.db.close();self.engine.dispose()


class InboundHarness:
    def __init__(self, sandbox, project_id, channel, monkeypatch, *responses):
        from app.core.config import settings
        from app.modules.ai_core.models import AIConfiguration
        from app.modules.sales_agent import live_service,active_service,commercial_context,understanding_service
        from app.modules.projects import sales_asset_service
        from app.modules.sales_crm import scheduling
        self.sandbox,self.db,self.clock=sandbox,sandbox.db,sandbox.clock
        self.project,self.lead,self.conversation=sandbox.conversation(project_id,channel)
        self.model=ScriptedModel(*responses);self.messenger=RecordingMessenger();self.calendar=FakeCalendar()
        self.monkeypatch=monkeypatch
        monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
        monkeypatch.setattr(settings,'SALES_UNDERSTANDING_PREVIEW_ENABLED',False)
        self.clock.install(monkeypatch,live_service,active_service,commercial_context,sales_asset_service,scheduling)
        self.db.add(AIConfiguration(company_id=None,agent_ventas={'model':'test/offline-scripted',
            'runtime_config':{'mode':'active','scope':'global','max_steps':8,'max_seconds':5}}))
        self.db.commit()

    @contextmanager
    def boundaries(self):
        from app.modules.sales_agent import live_service as live, active_service as active
        from app.modules.sales_agent.understanding_service import preview
        from app.integrations import gcalendar_client
        from app.modules.sales_crm import scheduling
        async def injected(*args,**kwargs):
            return await preview(*args,**kwargs,infer=self.model)
        def forbidden(*args,**kwargs):
            raise AssertionError('Offline sandbox attempted a real network/legacy boundary.')
        def aware(value):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        def busy(db,connection,*,starts_at,ends_at):
            return [(naive(e['start']),naive(e['end'])) for e in self.calendar.busy(connection.user_id,aware(starts_at),aware(ends_at))]
        def free(db,connection,*,starts_at,ends_at):
            return not busy(db,connection,starts_at=starts_at,ends_at=ends_at)
        def create(db,connection,*,start_time,end_time,event_id=None,**kwargs):
            key=event_id or 'synthetic-'+str(len(self.calendar.events)+1)
            value=self.calendar.create(connection.user_id,aware(start_time),aware(end_time),key=key)
            return {'id':value['provider_id'],'status':'confirmed'}
        def delete(db,connection,event_id):
            key=next((k for k,v in self.calendar.events.items() if v['provider_id']==event_id),event_id)
            self.calendar.delete(key)
        with ExitStack() as stack:
            for obj,attr,value in [(live,'SessionLocal',lambda:self.db),(self.db,'close',lambda:None),
                (active,'preview',injected),(live,'send_sms',self.messenger),(live,'send_message',self.messenger),
                (live,'build_sales_graph',forbidden),(live,'_schedule_next_action',lambda *a,**k:None),
                (socket.socket,'connect',forbidden),(socket.socket,'connect_ex',forbidden),
                (socket,'create_connection',forbidden),(socket,'getaddrinfo',forbidden)]:
                stack.enter_context(patch.object(obj,attr,value))
            for module in (gcalendar_client,scheduling):
                for name,fake in [('calendar_busy_ranges',busy),('is_calendar_free',free),
                                  ('create_calendar_event_for_connection',create),('delete_calendar_event_for_connection',delete)]:
                    if hasattr(module,name):stack.enter_context(patch.object(module,name,fake))
            yield

    def turn(self, text):
        from app.modules.sales_agent import live_service as live
        from app.modules.sales_agent.models import AgentRun, SalesMessage
        self.clock.advance(seconds=1)
        inbound=SalesMessage(conversation_id=self.conversation.id,channel=self.conversation.channel,
                             direction='inbound',role='user',content=text,status='received',created_at=self.clock.utcnow())
        self.db.add(inbound);self.db.commit()
        with self.boundaries():
            asyncio.run(live.process_live_inbound(self.conversation.id,inbound.id))
        run=self.db.query(AgentRun).filter_by(event_id='telnyx:'+inbound.id).one()
        self.db.refresh(self.conversation)
        return inbound,run

    def retry(self,inbound):
        from app.modules.sales_agent import live_service as live
        with self.boundaries():asyncio.run(live.process_live_inbound(self.conversation.id,inbound.id))

    def replies(self):
        from app.modules.sales_agent.models import SalesMessage
        return self.db.query(SalesMessage).filter_by(conversation_id=self.conversation.id,direction='outbound').order_by(SalesMessage.created_at,SalesMessage.id).all()
