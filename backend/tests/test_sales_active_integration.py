"""Real inbound coordinator/store/dispatcher; only network and cadence mocked."""
import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
import uuid
import pytest
from test_sales_turn_1720 import case, approved_asset, outbound
from app.core.config import settings
from app.modules.ai_core.models import AIConfiguration
from app.modules.projects.models import ProjectPropertyType, SalesAssetShare
from app.modules.sales_agent import active_service as active, live_service as live
from app.modules.sales_agent.models import AgentRun, SalesMessage, OutboundMessage
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
from app.modules.sales_agent.dialogue_store import Scope, load, save
from app.modules.sales_agent.understanding_contract import Understanding, DialogueState
from app.modules.sales_crm.models import Meeting


def understanding(text, *topics, subjects=None, references=None, alternatives=False, constraints=None, confidence=.99):
    requests=[dict(id='r'+str(i),topic=t,subject=(subjects or {}).get(i),polarity='request',evidence=text) for i,t in enumerate(topics)]
    return Understanding.model_validate(dict(version='sales-understanding/1.0',requests=requests,
        all_of=[] if alternatives else [r['id'] for r in requests],
        alternatives=[dict(id='or',request_ids=[r['id'] for r in requests],evidence=text)] if alternatives else [],
        constraints=constraints or [],references=references or [],preferences=[],
        requires_clarification=False,clarification_question=None,confidence=confidence))


class Harness:
    def __init__(self,case,monkeypatch):
        self.current_flow=False  # Historical coordinator-node compatibility harness.
        self.db,self.company,self.project,self.lead,self.conversation=case
        self.scope=Scope(self.company.id,self.project.id,self.conversation.id,self.lead.id)
        monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
        monkeypatch.setattr(settings,'SALES_UNDERSTANDING_PREVIEW_ENABLED',False)
        self.config=AIConfiguration(company_id=None,agent_ventas={'model':'test/offline',
            'runtime_config':dict(mode='active',company_ids=[self.company.id],project_ids=[self.project.id])})
        self.db.add(self.config);self.db.commit()
        self.infer=AsyncMock()
        self.send=AsyncMock(return_value={'sid':'accepted-test','status':'sent'})
        self.send.side_effect=lambda *args,**kwargs: {'sid':str(uuid.uuid4()),'status':'sent'}
        self.legacy=AsyncMock(side_effect=AssertionError('Active mode reached legacy graph'))

    @contextmanager
    def patched(self):
        from app.modules.sales_agent.understanding_service import preview as real
        async def injected(*args,**kwargs):return await real(*args,**kwargs,infer=self.infer)
        with patch('app.modules.sales_agent.next_flow.selected',return_value=self.current_flow),\
             patch.object(live,'SessionLocal',return_value=self.db),patch.object(self.db,'close'),\
             patch.object(active,'preview',side_effect=injected),patch.object(live,'send_sms',new=self.send),\
             patch.object(live,'send_message',new=self.send),\
             patch.object(live,'build_sales_graph',new=self.legacy),patch.object(live,'_schedule_next_action'):
            yield

    def turn(self,text,u):
        self.infer.return_value=u.model_dump_json() if isinstance(u,Understanding) else u
        inbound=SalesMessage(conversation_id=self.conversation.id,channel=self.conversation.channel,direction='inbound',role='user',content=text,status='received')
        self.db.add(inbound);self.db.commit()
        with self.patched():asyncio.run(live.process_live_inbound(self.conversation.id,inbound.id))
        return inbound,self.db.query(AgentRun).filter_by(event_id='telnyx:'+inbound.id).one()

    def retry(self,inbound):
        with self.patched():asyncio.run(live.process_live_inbound(self.conversation.id,inbound.id))

    def reply(self):
        return '\n\n'.join(m.content for m in self.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at))


@pytest.fixture
def agent(case,monkeypatch):return Harness(case,monkeypatch)


def test_active_real_dispatch_mixed_financing_materials_and_no_appointment(agent):
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure','floor_plan'])
    agent.project.profile.profile_data={'payment_methods':['Bank financing']}
    agent.project.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};agent.db.commit()
    text="Send plans and explain financing. I don't want an in-person visit yet."
    # Deliberately inconsistent high-confidence model label must be vetoed.
    u=understanding(text,'materials','financing','appointment',subjects={0:'floor_plan'})
    with patch.object(live,'_availability_reply',side_effect=AssertionError('Forbidden scheduling')):
        message,run=agent.turn(text,u)
    assert run.graph_version==active.ENGINE and run.status=='completed',run.output_snapshot
    assert agent.db.query(SalesAssetShare).one().sales_asset_id==asset.id
    assert 'Bank financing' in agent.reply() and '/projects/a/' in agent.reply()
    assert agent.reply().index('Bank financing')<agent.reply().index('/projects/a/')
    assert not agent.db.query(Meeting).count() and not agent.conversation.is_paused
    agent.legacy.assert_not_called()
    agent.retry(message)
    assert agent.infer.await_count==agent.send.await_count==1
    assert agent.db.query(SalesAssetShare).count()==1


@pytest.mark.parametrize('alternative,expected',[(False,2),(True,1)])
def test_and_or_materials_use_actual_approved_shares(agent,alternative,expected):
    for tags in [['brochure'],['gallery_image']]:
        approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),tags,name=tags[0])
    text='Send photos '+('or' if alternative else 'and')+' a brochure.'
    agent.turn(text,understanding(text,'materials','materials',subjects={0:'photos',1:'brochure'},alternatives=alternative))
    assert agent.db.query(SalesAssetShare).count()==expected


def test_explicit_exclusion_wins_over_bad_model_material_request(agent):
    for tags in [['brochure'],['gallery_image']]:
        approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),tags,name=tags[0])
    text='Send a brochure, but do not send photos.'
    agent.turn(text,understanding(text,'materials','materials',subjects={0:'brochure',1:'photos'}))
    shares=agent.db.query(SalesAssetShare).all()
    assert len(shares)==1 and 'brochure' in agent.reply() and 'gallery_image —' not in agent.reply()


def test_photo_fallback_requires_assent_then_shares_only_offered_file(agent):
    case=(agent.db,agent.company,agent.project,agent.lead,agent.conversation)
    chosen=approved_asset(case,['brochure'],name='Useful brochure')
    text='Could I see pictures?'
    agent.turn(text,understanding(text,'materials',subjects={0:'photos'}))
    assert agent.db.query(SalesAssetShare).count()==0
    assert 'Would you like that file?' in agent.reply()
    approved_asset(case,['floor_plan'],name='Unrequested plans')
    agent.turn('Yes',understanding('Yes','other'))
    assert [s.sales_asset_id for s in agent.db.query(SalesAssetShare)]==[chosen.id]


def test_unresolved_reference_cannot_share_or_schedule(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan'])
    text='Send plans for the second option.'
    ref=[dict(kind='ambiguous',expression='the second option',evidence='the second option')]
    agent.turn(text,understanding(text,'materials',subjects={0:'floor_plan'},references=ref))
    assert agent.db.query(SalesAssetShare).count()==0 and agent.db.query(Meeting).count()==0
    assert 'Which property option' in agent.reply()


def test_catalog_all_types_and_stable_selection_after_reordering(agent):
    rows=[ProjectPropertyType(project=agent.project,name=f'Type {i}',review_status='confirmed',sort_order=i) for i in range(7)]
    agent.db.add_all(rows);agent.db.commit()
    agent.turn('What types exist?',understanding('What types exist?','catalog'))
    assert '1. Type 0' in agent.reply() and '\n\n7. Type 6' in agent.reply()
    rows[0].sort_order=99;agent.db.commit()
    agent.turn('1',understanding('1','property_details',references=[dict(kind='property',expression='1',evidence='1')]))
    latest=agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc()).first()
    assert latest.metadata_json['selected_property_type_id']==rows[0].id
    assert 'Type 0' in latest.content and 'Type 6' not in latest.content


@pytest.mark.parametrize('output',["invalid json",'{"version":"invalid"}'])
def test_invalid_model_fails_closed_without_legacy_or_pause_and_keeps_evidence(agent,output):
    message,run=agent.turn('Send a brochure',output)
    assert run.graph_version==active.ENGINE and not agent.conversation.is_paused
    event=agent.db.query(SalesDialogueEvent).filter_by(event_key='active-understanding:'+message.id).one()
    assert event.payload_json['metadata']['outcome']=='invalid_model_contract'
    assert agent.db.query(SalesAssetShare).count()==agent.db.query(Meeting).count()==0
    agent.legacy.assert_not_called()


def test_retry_failed_delivery_reuses_durable_response_and_shares(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    agent.send.side_effect=RuntimeError('offline-test')
    text='Send a brochure'
    with pytest.raises(RuntimeError):agent.turn(text,understanding(text,'materials',subjects={0:'brochure'}))
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    run=agent.db.query(AgentRun).one()
    assert run.output_snapshot['reply_ready'] and run.status!='completed'
    original=run.output_snapshot['reply']
    assert not agent.db.query(SalesDialogueEvent).filter_by(event_key='active-receipt:'+inbound.id).count()
    agent.send.side_effect=None
    agent.retry(inbound)
    assert agent.db.query(SalesAssetShare).count()==agent.db.query(OutboundMessage).count()==1
    assert agent.infer.await_count==1
    assert agent.db.query(AgentRun).one().output_snapshot['reply']==original
    assert agent.db.query(AgentRun).one().status=='completed'


def test_manual_takeover_during_inference_stops_effects(agent):
    text='Send a brochure'
    async def take_over(*args):
        agent.conversation.is_paused=True;agent.conversation.pause_reason='Manual takeover';agent.db.commit()
        return understanding(text,'materials',subjects={0:'brochure'}).model_dump_json()
    agent.infer.side_effect=take_over
    agent.turn(text,understanding(text,'materials',subjects={0:'brochure'}))
    agent.send.assert_not_awaited()
    assert not agent.db.query(SalesAssetShare).count() and agent.conversation.is_paused


def test_retired_kill_switch_does_not_select_a_legacy_engine(agent,monkeypatch):
    scope=agent.scope
    assert active.selected_policy(agent.db,scope)
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',False)
    assert active.selected_policy(agent.db,scope)
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):agent.turn('Hello',understanding('Hello','other'))
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    agent.config.agent_ventas={'model':'test/offline'};agent.db.commit()
    agent.send.side_effect=lambda *args,**kwargs: {'sid':'recovered','status':'sent'}
    agent.retry(inbound)
    agent.legacy.assert_not_called()
    assert agent.send.await_count==2


@pytest.mark.parametrize('text',['STOP','Please let me speak to a human'])
def test_protected_controls_need_no_model_and_persist_before_reply(agent,text):
    agent.infer.side_effect=AssertionError('Protected controls must work without model')
    _,run=agent.turn(text,understanding(text,'other'))
    assert agent.conversation.is_paused and run.output_snapshot['metadata']['control_outcome'] in {'opt_out','handoff'}
    assert agent.send.await_count==1
    agent.infer.assert_not_awaited()


@pytest.mark.parametrize('selection',['1','3:00 PM'])
def test_verified_slot_booking_is_durable_and_retry_does_not_duplicate(agent,selection):
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    sales=User(company_id=agent.company.id,email='sales@test.example',hashed_password='test',role=UserRole.SALES,is_active=True,first_name='Sales')
    agent.db.add(sales);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=agent.project.id,user_id=sales.id,responsibility='sales',
        sales_enabled=True,accepts_appointments=True,is_active=True,accepts_new_leads=True))
    starts=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    agent.db.add(SalesAvailabilityBlock(user_id=sales.id,starts_at=starts,ends_at=starts+timedelta(hours=2),timezone='UTC'));agent.db.commit()
    agent.turn('I want to arrange a visit',understanding('I want to arrange a visit','appointment'))
    assert not agent.db.query(Meeting).count()
    message,run=agent.turn(selection,understanding(selection,'appointment',references=[dict(kind='appointment',expression=selection,evidence=selection)]))
    assert agent.db.query(Meeting).count()==1,run.output_snapshot
    meeting=agent.db.query(Meeting).one()
    assert meeting.meeting_time==starts and meeting.visit_address=='100 Main St'
    agent.retry(message)
    assert agent.db.query(Meeting).count()==1 and agent.infer.await_count==2


def test_revoked_approval_on_delivery_retry_drops_prepared_link(agent):
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    asset.approval_status='draft';agent.db.commit();agent.send.side_effect=None
    agent.retry(inbound)
    assert '/projects/a/' not in agent.send.await_args.kwargs['body']
    assert 'no longer approved' in agent.send.await_args.kwargs['body']


def test_active_followup_uses_no_legacy_model(agent):
    result=active.active_followup_result(agent.db,agent.scope)
    assert result['response_policy_trace']['engine']==active.ENGINE
    assert not result['proposed_actions'] and 'STOP' in result['proposed_reply']


def test_persistent_visit_prohibition_requires_explicit_reversal(agent):
    from app.modules.sales_agent.dialogue_tasks import prepare_tasks
    state=DialogueState(constraints=[dict(topic='appointment',scope='until_explicit_change',evidence='No visits yet')])
    text='I want a visit'
    state=prepare_tasks(state,understanding(text,'appointment'),'first')
    assert state.constraints
    text='I changed my mind; I want a visit now'
    u=understanding(text,'appointment').model_copy(update={'releases':[__import__('app.modules.sales_agent.understanding_contract',fromlist=['ConstraintRelease']).ConstraintRelease(topic='appointment',evidence=text)]})
    assert not prepare_tasks(state,u,'second').constraints


def test_virtual_tour_uses_approved_audited_destination_not_diagnostic_url(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['virtual_tour'],
        links=[{'url':'https://example.com/tour/?m=approved','kind':'virtual_tour','label':'360 tour'}])
    agent.turn('Send the virtual tour',understanding('Send the virtual tour','materials',subjects={0:'virtual_tour'}))
    shares=agent.db.query(SalesAssetShare).all()
    assert any(s.target_url=='https://example.com/tour/?m=approved' for s in shares)
    assert 'https://example.com/tour/' not in agent.reply() and '/projects/a/' in agent.reply()


def test_calendar_retry_is_scoped_and_uses_stable_event_id(agent):
    from app.modules.users.models import User,UserRole
    from app.modules.sales_crm.models import CalendarConnection,MeetingStatus
    user=User(company_id=agent.company.id,email='calendar@test.example',hashed_password='test',role=UserRole.SALES,is_active=True)
    agent.db.add(user);agent.db.flush()
    agent.db.add(CalendarConnection(user_id=user.id,provider='google',calendar_id='primary',status='connected'))
    meeting=Meeting(project_id=agent.project.id,lead_id=agent.lead.id,assigned_sales_user_id=user.id,
        meeting_time=datetime.utcnow()+timedelta(days=2),status=MeetingStatus.CONFIRMED,source='agent_sms_active',
        calendar_sync_status='failed',visit_address='100 Main St')
    agent.db.add(meeting);agent.db.commit()
    def transport(*args,**kwargs):return {'id':kwargs['event_id'],'htmlLink':'https://calendar.example/event'}
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=transport) as send:
        active.retry_active_calendars(agent.db)
        active.retry_active_calendars(agent.db)
    assert send.call_count==1
    assert meeting.calendar_sync_status=='synced' and meeting.gcal_event_id=='bp'+meeting.id.replace('-','')
