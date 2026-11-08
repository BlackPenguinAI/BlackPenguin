"""End-to-end active coordinator journeys with mocked model and provider only."""
import json
from unittest.mock import patch
from test_sales_active_integration import agent, understanding
from test_sales_turn_1720 import case
from app.modules.projects.models import ProjectPropertyType
from app.modules.sales_agent.models import AgentRun, SalesMessage, SalesFollowUpJob
from app.modules.sales_crm.models import LeadScoreSnapshot, Meeting
from app.modules.sales_agent import active_service as active
from app.modules.sales_agent.sales_policy import policy_context, custom_compliance, missing_fields
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.company_onboarding.models import CompanyProfile


def facts(agent, data):
    agent.project.profile.profile_data=data
    agent.project.profile.field_states={k:{'status':'confirmed','applicable':True} for k in data}
    agent.db.commit()


def answer(text, key):
    return Understanding.model_validate(dict(version='sales-understanding/1.0',requests=[],all_of=[],
        alternatives=[],constraints=[],references=[],preferences=[dict(key=key,value=text,evidence=text)],
        requires_clarification=False,clarification_question=None,confidence=.99))


def test_catalog_qualification_location_price_and_handoff_journey(agent):
    facts(agent,{'qualification_rules':'Confirm budget, purchase timeline, financing status, preferred unit type, and readiness to schedule a visit.',
                 'exact_address':'1 Main Street','city':'Virginia Beach','country':'US'})
    a=ProjectPropertyType(project=agent.project,name='Home A',review_status='confirmed',starting_price=100,currency='USD')
    b=ProjectPropertyType(project=agent.project,name='Home B',review_status='confirmed',starting_price=200,currency='USD')
    agent.db.add_all([a,b]);agent.db.commit()
    agent.turn('Available properties?',understanding('Available properties?','inventory'))
    assert 'budget range' in agent.reply()
    agent.turn('USD 150000 cash buyer',answer('USD 150000 cash buyer','budget'))
    assert 'planning to buy' in agent.reply()
    agent.turn('This month',answer('This month','purchase_timeline'))
    agent.turn('Paying cash',answer('Paying cash','financing'))
    agent.turn('Home A',understanding('Home A','property_details',references=[dict(kind='property',expression='Home A',evidence='Home A')]))
    agent.turn('What is its price?',understanding('What is its price?','pricing'))
    latest=agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc()).first()
    assert '100.00 USD' in latest.content and '200.00 USD' not in latest.content
    agent.turn('Where is it?',understanding('Where is it?','location'))
    assert '1 Main Street, Virginia Beach, US' in agent.reply()
    assert agent.lead.intent_score>0
    assert agent.db.query(LeadScoreSnapshot).count()==7
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').order_by(SalesMessage.created_at.desc()).first()
    agent.retry(inbound)
    assert agent.db.query(LeadScoreSnapshot).count()==7
    assert agent.db.query(Meeting).count()==0  # preferences are not booking consent
    agent.turn('I want to speak to a human',understanding('I want to speak to a human','human'))
    assert agent.conversation.is_paused and agent.lead.agent_status=='human_control'


def test_compliance_holds_the_action_without_pausing_or_booking(agent):
    facts(agent,{'compliance_notes':['Human approval required for financing claims']})
    agent.turn('What financing is available?',understanding('What financing is available?','financing'))
    agent.infer.assert_awaited_once()
    assert not agent.conversation.is_paused
    assert agent.db.query(Meeting).count()==0
    assert 'Sales team' in agent.reply()


def test_company_restrictions_are_scoped_and_cannot_be_waived_by_project(agent):
    profile=CompanyProfile(company_id=agent.company.id,final_approved=True,
        profile_data={'corporate_compliance_information':'Legal review needed'},
        field_states={'corporate_compliance_information':{'status':'confirmed'}})
    agent.db.add(profile);agent.db.commit()
    policy=policy_context(agent.db,agent.scope,{'compliance_notes':'Use standard Company compliance; no Project-specific notes'})
    assert custom_compliance(policy)
    profile.field_states={'corporate_compliance_information':{'status':'deferred'}};agent.db.commit()
    assert not custom_compliance(policy_context(agent.db,agent.scope,{}))


def test_intelligence_does_not_modify_runtime_config_or_commit_early(agent):
    before=json.loads(json.dumps(agent.config.agent_ventas))
    with patch('app.modules.sales_crm.intelligence.get_ai_config',side_effect=AssertionError('Mutating accessor')):
        agent.turn('I am a cash buyer',answer('I am a cash buyer','financing'))
    assert agent.config.agent_ventas==before
    assert agent.db.query(LeadScoreSnapshot).count()==1


def test_followup_uses_approved_rules_and_scoring_does_not_invent_completed_qualification(agent):
    facts(agent,{'qualification_rules':'Confirm budget and purchase timeline'})
    agent.turn('Hello',understanding('Hello','other'))
    result=active.active_followup_result(agent.db,agent.scope)
    assert 'planning to buy' in result['proposed_reply']
    assert missing_fields(agent.lead,agent.project.profile.profile_data)==['budget','purchase_timeline']
    assert agent.db.query(Meeting).count()==0


def test_low_confidence_does_not_write_unconfirmed_qualification(agent):
    u=answer('USD 100000','budget').model_copy(update={'confidence':.1})
    agent.turn('USD 100000',u)
    assert 'budget' not in (agent.lead.lead_profile_data or {}).get('facts',{})
    assert agent.db.query(LeadScoreSnapshot).count()==0


def test_active_cadence_refreshes_previous_cold_followup_without_changing_config(agent):
    from datetime import datetime, timedelta
    from app.modules.sales_agent.live_service import _schedule_next_action
    old=datetime.utcnow()+timedelta(days=14)
    job=SalesFollowUpJob(conversation_id=agent.conversation.id,idempotency_key='test-cadence',
                         scheduled_at=old,status='pending',reason='cold_cadence')
    agent.db.add(job);agent.lead.intent_tier='hot';agent.db.commit()
    before=json.loads(json.dumps(agent.config.agent_ventas))
    _schedule_next_action(agent.db,agent.conversation,agent.lead,'test',refresh_pending=True)
    assert job.reason=='hot_cadence' and job.scheduled_at<old
    assert agent.config.agent_ventas==before


def test_final_qualification_answer_is_acknowledged_without_booking(agent):
    facts(agent,{'qualification_rules':'Confirm budget'})
    agent.turn('USD 100000',answer('USD 100000','budget'))
    assert 'recorded that information' in agent.reply()
    assert 'I need clarification' not in agent.reply()
    assert agent.db.query(Meeting).count()==0
