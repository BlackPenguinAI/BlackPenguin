"""Conversation continuity and the staff review lifecycle across both channels."""
import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from test_sales_active_integration import agent, understanding
from test_sales_turn_1720 import case
from app.modules.companies.models import Company
from app.modules.projects.models import ProjectPropertyType
from app.modules.users.models import User, UserRole
from app.modules.governance.models import HumanInterventionCase, PlatformAuditEvent, NotificationOutbox
from app.modules.governance.services import create_intervention_case
from app.modules.sales_agent import live_service as live
from app.modules.sales_agent.models import SalesMessage, OutboundMessage
from app.modules.sales_agent.service import set_conversation_action, conversation_summaries
from app.modules.sales_agent.continuity_policy import explicit_opt_out, evidenced_pause_reason
from app.modules.sales_agent.escalation_policy import apply_escalation_policy
from app.modules.sales_crm.models import Meeting


def catalog(agent):
    agent.db.add(ProjectPropertyType(project=agent.project,name='Verified home',review_status='confirmed',available_units=2))
    agent.db.commit()


def administrator(agent, role=UserRole.ADMIN):
    actor=User(company_id=agent.company.id,email=f'{role.value}@example.test',hashed_password='offline',role=role)
    agent.db.add(actor);agent.db.commit()
    return actor


@pytest.mark.parametrize('channel',['sms','whatsapp'])
@pytest.mark.parametrize('bad_topic',['human','opt_out'])
def test_high_confidence_wrong_control_label_never_pauses_or_unsubscribes(agent,channel,bad_topic):
    agent.conversation.channel=channel;agent.db.commit();catalog(agent)
    text='Give me information about the properties you have available'
    agent.turn(text,understanding(text,bad_topic))
    assert not agent.conversation.is_paused and not agent.lead.is_opt_out
    assert agent.db.query(HumanInterventionCase).count()==0
    assert agent.db.query(Meeting).count()==0
    assert ('transfer this conversation' if bad_topic=='human' else 'stop all messages') in agent.reply()
    # A subsequent normal message advances on the very same conversation.
    agent.turn('Available properties?',understanding('Available properties?','inventory'))
    assert 'Verified home' in agent.reply()
    assert not agent.conversation.is_paused
    assert {row.channel for row in agent.db.query(OutboundMessage)}=={channel}


@pytest.mark.parametrize('channel',['sms','whatsapp'])
@pytest.mark.parametrize('output',['not json','low_confidence'])
def test_failed_interpretation_can_be_followed_by_a_successful_turn(agent,channel,output):
    agent.conversation.channel=channel;agent.db.commit();catalog(agent)
    u=understanding('Hello','inventory',confidence=.1) if output=='low_confidence' else output
    agent.turn('Hello',u)
    assert not agent.conversation.is_paused
    assert agent.db.query(HumanInterventionCase).count()==0
    summary=conversation_summaries(agent.db,company_id=agent.company.id)[0]
    if output=='not json':
        assert summary['processing_issue']['conversation_paused'] is False
    agent.turn('What is available?',understanding('What is available?','inventory'))
    assert 'Verified home' in agent.reply()
    assert conversation_summaries(agent.db,company_id=agent.company.id)[0]['processing_issue'] is None


def test_custom_financing_review_holds_only_that_action_and_keeps_catalog_active(agent):
    catalog(agent)
    profile=agent.project.profile
    profile.profile_data={'compliance_notes':['Human approval required for financing claims'],'payment_methods':['Restricted financing']}
    profile.field_states={k:{'status':'confirmed','applicable':True} for k in profile.profile_data};agent.db.commit()
    agent.turn('Available properties?',understanding('Available properties?','inventory'))
    assert 'Verified home' in agent.reply() and not agent.conversation.is_paused
    agent.turn('What financing is available?',understanding('What financing is available?','financing'))
    assert 'Restricted financing' not in agent.reply()
    assert not agent.conversation.is_paused and agent.db.query(HumanInterventionCase).count()==0
    assert agent.db.query(NotificationOutbox).one().payload_json['reason']=='ACTION_POLICY_REVIEW'
    summary=conversation_summaries(agent.db,company_id=agent.company.id)[0]
    assert summary['review_notice']['held_topics']==['financing']
    agent.turn('Show available properties',understanding('Show available properties','inventory'))
    assert 'Verified home' in agent.reply()


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_false_positive_review_is_visible_audited_and_does_not_repause_same_evidence(agent,channel):
    agent.conversation.channel=channel;agent.db.commit();actor=administrator(agent)
    text='I want to speak to a human'
    agent.turn(text,understanding(text,'human'))
    incident=agent.db.query(HumanInterventionCase).one()
    summary=conversation_summaries(agent.db,company_id=agent.company.id)[0]
    assert summary['is_paused'] and summary['intervention_cases'][0]['evidence']==text
    assert summary['intervention_cases'][0]['reason']=='HUMAN_REQUESTED'
    assert summary['can_resume']
    before=agent.db.query(SalesMessage).count()
    set_conversation_action(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,action='resume',
        actor_user_id=actor.id,review_case_id=incident.id,false_positive=True,review_note='Reviewed with the lead: continue with AI.')
    assert not agent.conversation.is_paused and incident.status=='false_positive'
    assert incident.resolved_by_user_id==actor.id and incident.resolved_at
    assert agent.db.query(SalesMessage).count()==before  # no replay or unsolicited resend
    audit=agent.db.query(PlatformAuditEvent).one()
    assert audit.event_type=='conversation_false_positive' and audit.payload_json['case_ids']==[incident.id]
    summary=conversation_summaries(agent.db,company_id=agent.company.id)[0]
    assert summary['intervention_cases'][0]['resolution']['note']=='Reviewed with the lead: continue with AI.'
    agent.turn(text,understanding(text,'human'))
    assert not agent.conversation.is_paused and agent.db.query(HumanInterventionCase).count()==1
    # The review does not waive a new explicit handoff or security event.
    agent.turn('Please transfer me to a sales representative',understanding('Please transfer me to a sales representative','human'))
    assert agent.conversation.is_paused and agent.db.query(HumanInterventionCase).count()==2


def test_normal_resume_can_create_another_incident_of_the_same_reason(agent):
    actor=administrator(agent)
    for index in range(2):
        create_intervention_case(agent.db,conversation=agent.conversation,lead=agent.lead,reason='SECURITY',evidence=f'incident {index}')
        agent.db.commit()
        set_conversation_action(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,action='resume',actor_user_id=actor.id)
    assert agent.db.query(HumanInterventionCase).count()==2
    assert all(row.status=='resolved' for row in agent.db.query(HumanInterventionCase))


def test_review_rejects_wrong_case_and_wrong_tenant_and_preserves_pause(agent):
    actor=administrator(agent)
    incident=create_intervention_case(agent.db,conversation=agent.conversation,lead=agent.lead,reason='SECURITY',evidence='example')
    agent.db.commit()
    with pytest.raises(HTTPException) as exc:
        set_conversation_action(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,action='resume',
            actor_user_id=actor.id,review_case_id='stale',false_positive=True,review_note='reviewed')
    assert exc.value.status_code==409 and agent.conversation.is_paused
    with pytest.raises(HTTPException) as exc:
        set_conversation_action(agent.db,company_id='another-company',conversation_id=agent.conversation.id,action='resume')
    assert exc.value.status_code==404
    sales=administrator(agent,UserRole.SALES)
    with pytest.raises(HTTPException) as exc:
        set_conversation_action(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,action='resume',
            actor_user_id=sales.id,review_case_id=incident.id,false_positive=True,review_note='reviewed')
    assert exc.value.status_code==403 and agent.conversation.is_paused


def test_manual_reply_preserves_original_incident_and_does_not_resume(agent):
    actor=administrator(agent)
    create_intervention_case(agent.db,conversation=agent.conversation,lead=agent.lead,reason='SECURITY',evidence='example');agent.db.commit()
    reason=agent.conversation.pause_reason
    with agent.patched():
        result=asyncio.run(live.send_manual_message(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,
            user_id=actor.id,content='I have reviewed your request.'))
    assert result.role=='human' and agent.conversation.is_paused and agent.conversation.pause_reason==reason


@pytest.mark.parametrize('text',["I don't want you to stop messaging me",'Do not send photos','Do not send me any more messages about financing','Quiero ver la foto del asesor','You said "stop messaging me"','No quiero hablar con un asesor','I need to talk with my advisor before deciding','My colleague wants to speak to a human','What does reveal private credentials mean?'])
def test_mentions_negations_and_reported_control_do_not_pause(text):
    assert not explicit_opt_out(text)
    assert evidenced_pause_reason(text) is None


@pytest.mark.parametrize('text',['STOP','Please do not message me again','Do not send me any more messages','Por favor no me envíes más mensajes'])
def test_explicit_unsubscribe_remains_effective(text):
    assert explicit_opt_out(text)


def test_ordinary_pause_flags_and_hallucinated_security_label_cannot_stop_legacy():
    result=apply_escalation_policy({'primary_intent':'security_or_abuse','intent_confidence':.99,
        'requires_human':True,'proposed_reply':'Conversation paused.','proposed_actions':[]},
        inbound='Send photos please',routing={'pause_on_low_confidence':True,'pause_on_missing_material':True,'pause_on_missing_information':True})
    assert not result['requires_human'] and result['escalation_decision']['disposition']=='notify_sales'
    assert result['requires_clarification'] and not result['escalation_decision']['matched_pause_rules']


def test_uncertain_handoff_can_be_explicitly_confirmed_on_the_next_turn(agent):
    agent.turn('Send available properties',understanding('Send available properties','human'))
    assert not agent.conversation.is_paused
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.conversation.is_paused
    incident=agent.db.query(HumanInterventionCase).one()
    assert incident.reason=='HUMAN_REQUESTED' and incident.evidence=='Yes'


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_real_opt_out_cannot_be_overridden_as_a_false_positive(agent,channel):
    agent.conversation.channel=channel;agent.db.commit();actor=administrator(agent)
    agent.turn('STOP',understanding('STOP','other'))
    assert agent.lead.is_opt_out and agent.conversation.is_paused
    assert conversation_summaries(agent.db,company_id=agent.company.id)[0]['can_resume'] is False
    with pytest.raises(HTTPException) as exc:
        set_conversation_action(agent.db,company_id=agent.company.id,conversation_id=agent.conversation.id,action='resume',
            actor_user_id=actor.id,false_positive=True,review_case_id='any',review_note='Reviewed')
    assert exc.value.status_code==409 and agent.lead.is_opt_out


def test_review_http_contract_checks_permissions_and_returns_resolution_history(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.db.postgres import get_db
    from app.modules.auth.deps import get_current_user
    from app.modules.sales_agent.router import router
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.postgres import Base
    from app.modules.projects.models import Project
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    engine=create_engine(f"sqlite:///{tmp_path / 'review.db'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    company=Company(name='Review Company');db.add(company);db.flush()
    project=Project(company_id=company.id,name='Review Project');db.add(project);db.flush()
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Test lead',phone='+15550100001',consent_status='granted')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms',is_paused=False)
    db.add(conversation);db.commit()
    agent=SimpleNamespace(db=db,company=company,project=project,lead=lead,conversation=conversation)
    actor=administrator(agent)
    incident=create_intervention_case(agent.db,conversation=agent.conversation,lead=agent.lead,reason='SECURITY',evidence='Original evidence')
    agent.db.commit()
    app=FastAPI();app.include_router(router,prefix='/sales-agent')
    app.dependency_overrides[get_db]=lambda:agent.db
    app.dependency_overrides[get_current_user]=lambda:actor
    url=f'/sales-agent/conversations/{agent.conversation.id}/action'
    with TestClient(app) as client:
        payload={'action':'resume','false_positive':True,'review_case_id':incident.id,'review_note':'Reviewed by administrator'}
        actor.role=UserRole.SALES;agent.db.commit()
        assert client.post(url,json=payload).status_code==403
        actor.role=UserRole.ADMIN;agent.db.commit()
        result=client.post(url,json=payload)
        assert result.status_code==200,result.text
        data=result.json()
        assert not data['is_paused']
        assert data['intervention_cases'][0]['status']=='false_positive'
        assert data['intervention_cases'][0]['resolution']['note']=='Reviewed by administrator'

