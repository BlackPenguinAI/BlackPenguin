import asyncio
from datetime import datetime,timedelta
from unittest.mock import patch
from test_sales_turn_1720 import case,approved_asset,outbound
from test_sales_active_integration import agent,understanding
from app.modules.sales_agent import live_service as live
from app.modules.sales_agent.models import SalesMessage
from app.modules.projects.models import SalesAssetShare
from app.modules.sales_agent.dialogue_store import save,load
from app.modules.sales_agent.understanding_contract import DialogueState,Reference
from app.modules.sales_agent.dialogue_shadow import recorded_offers
from app.modules.sales_agent.dialogue_tasks import resolve_reference


def test_stop_must_apply_even_when_active_conversation_is_manually_paused(agent):
    agent.conversation.is_paused=True
    agent.conversation.pause_reason='Manual takeover'
    message=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='STOP',status='received')
    agent.db.add(message);agent.db.commit()
    with agent.patched():asyncio.run(live.process_live_inbound(agent.conversation.id,message.id))
    agent.db.refresh(agent.lead)
    assert agent.lead.is_opt_out, 'STOP was ignored because the active conversation was already paused.'


def test_resumed_approved_material_need_is_fulfilled_without_repeating_request(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    old=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='Please send the brochure',status='received')
    agent.db.add(old);agent.db.commit()
    state=DialogueState(tasks=[dict(id='interrupted-material',topic='materials',subject='brochure',status='suspended',source_message_id=old.id)])
    save(agent.db,agent.scope,event_key='interrupted',expected_revision=0,state=state);agent.db.commit()
    agent.turn('Also explain financing',understanding('Also explain financing','financing'))
    assert agent.db.query(SalesAssetShare).count()==1, 'The resumed read found material, but current-message-only dispatch did not share it.'


def test_unique_offered_time_can_resolve_explicit_time_not_only_ordinal(agent):
    slot=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    outbound(agent.db,agent.conversation,'Available: 3:00 PM UTC',{'appointment_offer':{'slots':[slot.isoformat()]}})
    state=DialogueState(offers=recorded_offers(agent.db,agent.conversation))
    result=resolve_reference(agent.db,agent.scope,state,Reference(kind='appointment',expression='3:00 PM',evidence='3:00 PM'))
    assert result and result['id']==slot.isoformat(), 'An explicit unique offered appointment time is not resolved.'

import pytest
from app.modules.sales_agent.runtime_policy import RuntimePolicy
from app.modules.sales_agent.dialogue_store import Scope


def test_global_policy_includes_current_and_future_ids_without_wildcards():
    import uuid
    policy=RuntimePolicy(mode='active',scope='global')
    for _ in range(3):
        assert policy.selects(Scope(*(str(uuid.uuid4()) for _ in range(4))))
    assert RuntimePolicy(mode='disabled',scope='global').selects(Scope('a','b','c','d'))


@pytest.mark.parametrize('field',['company_ids','project_ids','lead_ids'])
def test_global_rejects_conflicting_filters(field):
    import uuid
    assert RuntimePolicy(mode='active',scope='global',**{field:[str(uuid.uuid4())]}).scope == 'global'


def test_global_mode_is_not_inferred_from_empty_cohort():
    assert RuntimePolicy(mode='active').scope == 'global'


def test_global_engine_processes_a_new_company_without_republishing_ids(agent):
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project,ProjectProfile
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    agent.config.agent_ventas={'model':'test/offline','runtime_config':{'mode':'active','scope':'global'}}
    agent.db.commit()
    agent.turn('Hello',understanding('Hello','other'))
    company=Company(name='Future company');agent.db.add(company);agent.db.flush()
    project=Project(company_id=company.id,name='Future project',timezone='UTC')
    project.profile=ProjectProfile(profile_data={},field_states={});agent.db.add(project);agent.db.flush()
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Future test',phone='+15550100002',source='manual',platform='manual',consent_status='granted')
    agent.db.add(lead);agent.db.flush()
    conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms',provider='telnyx',provider_thread_key='new-company',is_paused=False)
    agent.db.add(conversation);agent.db.commit()
    agent.company,agent.project,agent.lead,agent.conversation=company,project,lead,conversation
    _,run=agent.turn('Hello',understanding('Hello','other'))
    assert run.graph_version=='sales-active/1.0'
    agent.legacy.assert_not_called()


@pytest.mark.parametrize('word',['STOP','UNSUBSCRIBE','CANCEL','END','QUIT'])
def test_paused_optout_is_idempotent_without_model(agent,word):
    agent.conversation.is_paused=True;agent.conversation.pause_reason='Manual takeover';agent.db.commit()
    agent.infer.side_effect=AssertionError('Optout must not call the model')
    message,run=agent.turn(word,understanding(word,'other'))
    assert agent.lead.is_opt_out and agent.lead.consent_status=='opted_out'
    agent.retry(message)
    assert agent.send.await_count==1
    agent.infer.assert_not_awaited()


def test_same_clock_time_on_two_offered_dates_requires_clarification(agent):
    slot=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    outbound(agent.db,agent.conversation,'Two days at 3:00 PM',{'appointment_offer':{'slots':[slot.isoformat(),(slot+timedelta(days=1)).isoformat()]}})
    state=DialogueState(offers=recorded_offers(agent.db,agent.conversation))
    assert resolve_reference(agent.db,agent.scope,state,Reference(kind='appointment',expression='3:00 PM',evidence='3:00 PM')) is None


def test_current_exclusion_blocks_resumed_material(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    state=DialogueState(tasks=[dict(id='old',topic='materials',subject='brochure',status='suspended')])
    save(agent.db,agent.scope,event_key='old',expected_revision=0,state=state);agent.db.commit()
    text='Do not send the brochure'
    u=understanding(text,'materials',subjects={0:'brochure'})
    agent.turn(text,u)
    assert agent.db.query(SalesAssetShare).count()==0
