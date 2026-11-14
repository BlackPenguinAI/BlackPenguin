"""Sender reuse preserves tenant history and permanently retires old routing."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from test_live_sales_agent import _db
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.models import TelnyxCompanyConfig
from app.modules.system_settings.services import disconnect_telnyx_company_config
from app.modules.sales_agent.models import SalesConversation,SalesMessage,SalesInboundJob,SalesFollowUpJob,OutboundMessage
from app.modules.sales_agent import live_service as live
from app.modules.sales_agent.provider_routes import release_stale_conflict,retired,assert_dispatchable
from app.modules.sales_agent.service import set_conversation_action
from app.modules.sales_agent.conversation_scope import scoped_messages_query
from app.modules.sales_agent.provider_router import _apply_status

SENDER='+15550100002';PHONE='+15550100001'

@pytest.fixture(params=['sms','whatsapp'])
def route_case(request):
    db=_db();old_company=Company(name='Old company');new_company=Company(name='New company');db.add_all([old_company,new_company]);db.flush()
    old_project=Project(company_id=old_company.id,name='Old');new_project=Project(company_id=new_company.id,name='New');db.add_all([old_project,new_project]);db.flush()
    old_lead=Lead(company_id=old_company.id,project_id=old_project.id,full_name='Old lead',phone='deleted-anonymized',preferred_channel=request.param,source='manual',consent_status='granted',deleted_at=datetime.utcnow())
    new_lead=Lead(company_id=new_company.id,project_id=new_project.id,full_name='New lead',phone=PHONE,source='manual',consent_status='granted',preferred_channel=request.param)
    db.add_all([old_lead,new_lead]);db.flush()
    channel=request.param;key=f'telnyx:{SENDER}:{PHONE}' if channel=='sms' else f'telnyx:whatsapp:{SENDER}:{PHONE}'
    conversation=SalesConversation(company_id=old_company.id,project_id=old_project.id,lead_id=old_lead.id,provider='telnyx',channel=channel,provider_thread_key=key,is_paused=True,pause_reason='Lead deleted by an authorized administrator')
    db.add(conversation);db.flush()
    message=SalesMessage(conversation_id=conversation.id,channel=channel,direction='inbound',role='user',content='PRIVATE OLD COMPANY MESSAGE',status='received');db.add(message);db.flush()
    db.add(SalesMessage(conversation_id=conversation.id,channel=channel,direction='outbound',role='assistant',content='Historical receipt',status='sent',provider_message_id='old-provider-receipt'))
    db.add(SalesInboundJob(conversation_id=conversation.id,message_id=message.id,status='pending'))
    db.add(SalesFollowUpJob(conversation_id=conversation.id,kind='test',reason='test',idempotency_key='old-followup',status='pending',scheduled_at=datetime.utcnow()))
    db.add(OutboundMessage(conversation_id=conversation.id,idempotency_key='old-pending',provider='telnyx',channel=channel,content='Old pending',status='queued'))
    before=TelnyxCompanyConfig(company_id=old_company.id)
    after=TelnyxCompanyConfig(company_id=new_company.id,from_phone_number=SENDER if channel=='sms' else None,whatsapp_from_phone_number=SENDER if channel=='whatsapp' else None,live_sms_enabled=channel=='sms',live_whatsapp_enabled=channel=='whatsapp',verification_status='verified',whatsapp_verification_status='verified')
    db.add_all([before,after]);db.commit()
    yield db,conversation,old_lead,new_lead,before,after,key
    db.close()


def test_new_intake_retires_stale_route_without_reassigning_old_history(route_case,monkeypatch):
    db,old,old_lead,lead,before,after,key=route_case
    old_id,old_company,old_project=old.id,old.company_id,old.project_id
    inflight=OutboundMessage(conversation_id=old.id,idempotency_key='old-inflight',provider='telnyx',channel=old.channel,content='Already started',status='sending',provider_message_id='inflight-receipt')
    db.add(inflight);db.commit()
    monkeypatch.setattr(live,'channel_sender',lambda *args,**kwargs:SENDER)
    conversation,created=live.get_or_create_live_conversation(db,lead,provider='telnyx');db.commit()
    assert created and conversation.id!=old_id and conversation.company_id==lead.company_id
    db.refresh(old)
    assert retired(old) and old.provider_thread_key is None
    assert old.company_id==old_company and old.project_id==old_project and old.lead_id==old_lead.id
    assert old.continuity_json['retired_provider_route']['provider_thread_key']==key
    assert all('PRIVATE OLD' not in m.content for m in scoped_messages_query(db,conversation))
    assert db.query(SalesInboundJob).filter_by(conversation_id=old.id).one().status=='cancelled'
    assert db.query(SalesFollowUpJob).filter_by(conversation_id=old.id).one().status=='cancelled'
    assert db.query(OutboundMessage).filter_by(idempotency_key='old-pending').one().status=='cancelled'
    db.refresh(inflight);assert inflight.status=='sending' and inflight.provider_message_id=='inflight-receipt'
    assert live.resolve_inbound_conversation(db,provider='telnyx',channel=old.channel,to_number=SENDER,from_number=PHONE).id==conversation.id
    _apply_status(db,provider='telnyx',message_id='old-provider-receipt',status='delivered')
    assert db.query(SalesMessage).filter_by(provider_message_id='old-provider-receipt').one().status=='delivered'
    with pytest.raises(HTTPException):set_conversation_action(db,company_id=old_company,conversation_id=old_id,action='resume')
    with pytest.raises(HTTPException):live.get_or_create_live_conversation(db,old_lead,provider='telnyx')


def test_paused_or_deleted_lead_is_not_enough_to_steal_an_owned_sender(route_case):
    db,old,old_lead,lead,before,after,key=route_case
    if old.channel=='sms':after.from_phone_number=None
    else:after.whatsapp_from_phone_number=None
    db.flush()
    if old.channel=='sms':before.from_phone_number=SENDER
    else:before.whatsapp_from_phone_number=SENDER
    db.commit()
    conflict=release_stale_conflict(db,thread_key=key,company_id=lead.company_id,provider='telnyx',channel=old.channel)
    assert conflict.id==old.id and not retired(old) and old.provider_thread_key==key


def test_unverified_new_company_cannot_release_history(route_case):
    db,old,_,lead,_,after,key=route_case
    after.verification_status=after.whatsapp_verification_status='not_configured';db.commit()
    assert release_stale_conflict(db,thread_key=key,company_id=lead.company_id,provider='telnyx',channel=old.channel).id==old.id
    assert not retired(old)


def test_disconnect_retires_route_and_rollback_keeps_original_binding(route_case):
    db,old,_,lead,before,after,key=route_case
    release_stale_conflict(db,thread_key=key,company_id=lead.company_id,provider='telnyx',channel=old.channel);db.rollback();db.refresh(old)
    assert old.provider_thread_key==key and not retired(old)
    disconnect_telnyx_company_config(db,old.company_id,scope=old.channel)
    assert retired(old) and old.provider_thread_key is None


def test_retired_route_cannot_send_even_with_a_manual_or_booking_override(route_case,monkeypatch):
    db,old,old_lead,lead,_,_,key=route_case
    release_stale_conflict(db,thread_key=key,company_id=lead.company_id,provider='telnyx',channel=old.channel);db.commit()
    network=AsyncMock();monkeypatch.setattr(live,'send_sms',network);monkeypatch.setattr(live,'send_message',network)
    with pytest.raises(HTTPException):asyncio.run(live._dispatch_part(db,conversation=old,lead=old_lead,content='Must never send',role='assistant',agent_run_id=None,author_user_id='manual',metadata={'meeting_id':'old'}))
    network.assert_not_awaited()
    old.is_paused=False;db.flush()
    with pytest.raises(HTTPException):assert_dispatchable(db,old)
