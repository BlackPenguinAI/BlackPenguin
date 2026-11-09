import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from test_sales_turn_1720 import case, approved_asset
from test_sales_runtime_456 import inbound, scope, CASES
from test_staff_monitor import monitor
from app.core.config import settings
from app.modules.ai_core.models import AIConfiguration, PromptVersion
from app.modules.ai_core.services import validate_sales_configuration
from app.modules.sales_agent.runtime_policy import RuntimePolicy
from app.modules.sales_agent.dialogue_orchestrator import run_turn
from app.modules.sales_agent.dialogue_composer import compose
from app.modules.sales_agent.dialogue_shadow import observe_shadow
from app.modules.sales_agent.dialogue_store import save, load, Scope
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
from app.modules.sales_agent.understanding_contract import DialogueState, ToolResult
from app.modules.sales_agent.models import SalesMessage, OutboundMessage
from app.modules.sales_crm.models import Meeting


def policy_for(case):
    _,company,project,lead,_=case
    return dict(mode='shadow',company_ids=[company.id],project_ids=[project.id],lead_ids=[lead.id])


@pytest.mark.parametrize('values',[{'max_steps':31},
    {'max_steps':True},{'max_seconds':float('nan')},{'max_seconds':True},
    {'unknown':True}])
def test_invalid_rollout_is_rejected_with_human_message(values):
    with pytest.raises(HTTPException) as e:
        validate_sales_configuration({'runtime_config':values})
    assert e.value.status_code==422 and isinstance(e.value.detail,str)


def test_cohort_requires_company_and_project_and_optional_lead(case):
    p=RuntimePolicy(**policy_for(case));s=scope(case)
    assert p.selects(s)
    assert p.selects(Scope('foreign',s.project_id,s.conversation_id,s.lead_id))
    assert p.selects(Scope(s.company_id,'foreign',s.conversation_id,s.lead_id))
    assert p.selects(Scope(s.company_id,s.project_id,s.conversation_id,'foreign'))
    assert RuntimePolicy().selects(s)


@pytest.mark.parametrize('scenario',CASES,ids=lambda c:c['id'])
def test_composition_of_scripted_cases_makes_no_effect_claims(case,monkeypatch,scenario):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    message,u=inbound(case,scenario)
    outcome=run_turn(case[0],scope(case),message_id=message.id,understanding=u,expected_revision=0,event_key='test')
    draft=compose(outcome)
    assert draft.text and all(len(part)<=1400 for part in draft.parts)
    assert 'have sent' not in draft.text and 'appointment confirmed' not in draft.text
    assert case[0].query(OutboundMessage).count()==0


def test_catalog_is_complete_and_money_currencies_stay_separate():
    rows=[dict(id=str(i),property_type=f'Type {i}',bedrooms=i,starting_price=10000+i,currency='USD' if i%2 else 'MXN') for i in range(1,12)]
    state=DialogueState(tasks=[dict(id='catalog',topic='catalog',status='completed')])
    result=ToolResult(operation_id='catalog',status='partial',data={'property_types':rows})
    draft=compose(SimpleNamespace(state=state,results=[result]))
    assert 'Confirmed catalog:\n\n1. Type 1' in draft.text
    assert '\n\n11. Type 11' in draft.text
    assert 'USD' in draft.text and 'MXN' in draft.text and 'partial' in draft.text


def test_excluded_material_cannot_appear_in_composed_draft():
    state=DialogueState(tasks=[dict(id='photos',topic='materials',subject='photos',status='pending')],
        constraints=[dict(topic='materials',subject='photos',scope='turn',evidence='No photos')])
    result=ToolResult(operation_id='photos',status='success',data={'materials':[{'asset_id':'x','name':'Forbidden photo','content_tags':['gallery_image']}]})
    draft=compose(SimpleNamespace(state=state,results=[result]))
    assert not draft.asset_ids and 'Forbidden photo' not in draft.text


@pytest.mark.parametrize('value',[{'internal':'object'},[{'internal':'object'}]])
def test_unexpected_fact_shape_fails_closed(value):
    state=DialogueState(tasks=[dict(id='a',topic='financing',status='completed')])
    draft=compose(SimpleNamespace(state=state,results=[ToolResult(operation_id='a',status='success',data={'value':value})]))
    assert draft.violations==('unsupported_fact_shape',) and 'internal' not in draft.text


def setup_shadow(case,monkeypatch):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    monkeypatch.setattr(settings,'SALES_UNDERSTANDING_PREVIEW_ENABLED',True)
    message,u=inbound(case)
    config=AIConfiguration(company_id=None,agent_ventas={'model':'test/offline','runtime_config':policy_for(case)})
    case[0].add(config);case[0].commit()
    return message,u,config


def test_shadow_executes_actual_pipeline_once_and_never_dispatches(case,monkeypatch):
    message,u,config=setup_shadow(case,monkeypatch)
    approved_asset(case,['brochure'])
    model=AsyncMock(return_value=u.model_dump_json())
    with patch('app.integrations.openrouter_client.generate_llm_response',new=model):
        # Inference injected at preview to avoid requiring any real credential.
        with patch('app.modules.sales_agent.dialogue_shadow.preview') as preview:
            from app.modules.sales_agent.understanding_service import preview as real
            async def fake(*args,**kwargs):return await real(*args,**kwargs,infer=AsyncMock(return_value=u.model_dump_json()))
            preview.side_effect=fake
            assert asyncio.run(observe_shadow(case[0],case[-1],message))=='recorded'
            case[0].commit()
            assert asyncio.run(observe_shadow(case[0],case[-1],message))=='replayed'
            assert preview.call_count==1
    events=case[0].query(SalesDialogueEvent).order_by(SalesDialogueEvent.revision).all()
    assert len(events)==3 and events[-1].payload_json['metadata']['not_dispatched']
    assert events[-1].payload_json['metadata']['draft']['asset_ids']
    assert 'Not sent yet' in events[-1].payload_json['metadata']['draft']['text']
    assert case[0].query(OutboundMessage).count()==case[0].query(Meeting).count()==0
    assert case[0].query(SalesMessage).count()==1 and not case[-1].is_paused


def test_draft_config_does_not_enable_shadow(case,monkeypatch):
    message,u,config=setup_shadow(case,monkeypatch)
    config.agent_ventas={'model':'test/offline'}
    case[0].add(PromptVersion(company_id=None,agent_key='sales',version_number=1,
        configuration={'runtime_config':policy_for(case)},is_published=False))
    case[0].commit()
    with patch('app.modules.sales_agent.dialogue_shadow.preview',new=AsyncMock()) as preview:
        assert asyncio.run(observe_shadow(case[0],case[-1],message))=='not_selected'
        preview.assert_not_awaited()


def test_global_kill_switch_returns_before_db(monkeypatch):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',False)
    assert asyncio.run(observe_shadow(None,None,None))=='disabled'


def test_shadow_failure_does_not_touch_legacy_state(case,monkeypatch):
    message,u,config=setup_shadow(case,monkeypatch)
    with patch('app.modules.sales_agent.dialogue_shadow.preview',new=AsyncMock(side_effect=RuntimeError('private-provider-value'))):
        assert asyncio.run(observe_shadow(case[0],case[-1],message))=='shadow_error'
    assert load(case[0],scope(case))[0]==1 and not case[-1].is_paused
    assert 'private-provider-value' not in str(case[0].query(SalesDialogueEvent).one().payload_json)


def test_monitor_exports_scoped_runtime_history_and_redacts(monitor):
    db,client,actor,company,project,foreign,lead,second,conv,*_=monitor
    s=Scope(company.id,project.id,conv.id,lead.id)
    save(db,s,event_key='draft',expected_revision=0,state=DialogueState(),
         metadata={'draft':{'text':'Diagnostic draft','password':'NEVER_EXPORT'}});db.commit()
    query=f'company_id={company.id}&project_id={project.id}&lead_id={lead.id}'
    response=client.get(f'/monitor/conversations/{conv.id}/export?{query}')
    assert response.status_code==200
    assert len(response.json()['dialogue_events'])==1
    assert 'NEVER_EXPORT' not in response.text
    detail=client.get(f'/monitor/conversations/{conv.id}?{query}')
    assert len(detail.json()['dialogue_events'])==1
    actor.role=__import__('app.modules.users.models',fromlist=['UserRole']).UserRole.ADMIN
    assert client.get(f'/monitor/conversations/{conv.id}?{query}').status_code==403


def test_mixed_answer_puts_known_text_before_material_proposals():
    state=DialogueState(tasks=[dict(id='file',topic='materials',status='pending'),
        dict(id='money',topic='financing',status='completed')])
    results=[ToolResult(operation_id='file',status='success',data={'materials':[{'asset_id':'x','name':'Approved brochure','content_tags':['brochure']}],'coverage_confirmed':True}),
             ToolResult(operation_id='money',status='success',data={'value':['Bank financing']})]
    text=compose(SimpleNamespace(state=state,results=results)).text
    assert text.index('Bank financing')<text.index('Approved brochure')


def test_missing_requested_fact_is_explicit_not_silently_omitted():
    state=DialogueState(tasks=[dict(id='money',topic='financing',status='blocked')])
    draft=compose(SimpleNamespace(state=state,results=[ToolResult(operation_id='money',status='empty')]))
    assert 'Financing: verified information' in draft.text and draft.pending_task_ids==('money',)


def test_runtime_policy_is_only_effective_after_publishing(case):
    from app.modules.ai_core.services import create_prompt_draft,publish_prompt_version
    from app.modules.sales_agent.default_prompt import SALES_AGENT_DEFAULT_CONFIG
    config=deepcopy(SALES_AGENT_DEFAULT_CONFIG);config['runtime_config']=policy_for(case)
    version=create_prompt_draft(case[0],company_id=None,agent_key='sales',configuration=config,change_note='test scoped shadow',actor_id=None)
    current=case[0].query(AIConfiguration).filter_by(company_id=None).one()
    assert RuntimePolicy.model_validate(current.agent_ventas.get('runtime_config') or {}).mode=='active'
    publish_prompt_version(case[0],company_id=None,agent_key='sales',version_id=version.id,actor_id=None)
    assert current.agent_ventas['runtime_config']==policy_for(case)


def test_recorded_offers_preserve_ids_and_plain_reply_invalidates_ordinals(case):
    from app.modules.sales_agent.dialogue_shadow import recorded_offers
    from test_sales_turn_1720 import outbound
    from app.modules.projects.models import ProjectPropertyType
    a=ProjectPropertyType(project=case[2],name='Studio',review_status='confirmed')
    b=ProjectPropertyType(project=case[2],name='Loft',review_status='confirmed')
    case[0].add_all([a,b]);case[0].commit()
    outbound(case[0],case[-1],'1. Loft 2. Studio',{'property_catalog_offer':{'property_type_ids':[b.id,a.id]}})
    assert recorded_offers(case[0],case[-1])[0].option_ids==[b.id,a.id]
    outbound(case[0],case[-1],'A new question without selectable options',seconds=1)
    assert recorded_offers(case[0],case[-1])==[]


def test_successful_shadow_obeys_caller_rollback(case,monkeypatch):
    message,u,config=setup_shadow(case,monkeypatch)
    from app.modules.sales_agent.understanding_service import preview as real
    async def injected(*args,**kwargs):return await real(*args,**kwargs,infer=AsyncMock(return_value=u.model_dump_json()))
    with patch('app.modules.sales_agent.dialogue_shadow.preview',side_effect=injected):
        assert asyncio.run(observe_shadow(case[0],case[-1],message))=='recorded'
    case[0].rollback()
    assert load(case[0],scope(case))[0]==0


def test_failed_interpretation_retry_does_not_charge_twice(case,monkeypatch):
    message,u,config=setup_shadow(case,monkeypatch)
    from app.modules.sales_agent.understanding_service import preview as real
    infer=AsyncMock(return_value='invalid JSON')
    async def injected(*args,**kwargs):return await real(*args,**kwargs,infer=infer)
    with patch('app.modules.sales_agent.dialogue_shadow.preview',side_effect=injected):
        assert asyncio.run(observe_shadow(case[0],case[-1],message))=='invalid_model_contract'
        case[0].commit()
        assert asyncio.run(observe_shadow(case[0],case[-1],message))=='invalid_model_contract'
    infer.assert_awaited_once()


def test_selected_live_worker_keeps_legacy_reply_and_records_shadow(case,monkeypatch):
    from test_sales_turn_1720 import run_live
    from app.modules.sales_agent.default_prompt import SALES_AGENT_DEFAULT_CONFIG
    message,u,config=setup_shadow(case,monkeypatch)
    config.agent_ventas={**deepcopy(SALES_AGENT_DEFAULT_CONFIG),'runtime_config':policy_for(case)}
    case[0].commit()
    from app.modules.sales_agent.understanding_service import preview as real
    async def injected(*args,**kwargs):return await real(*args,**kwargs,infer=AsyncMock(return_value=u.model_dump_json()))
    with patch('app.modules.sales_agent.dialogue_shadow.preview',side_effect=injected):
        dispatch,slots,graph,ids=run_live(case,message.content,{'proposed_reply':'LEGACY RESPONSE','primary_intent':'general_question','intent_confidence':.99})
    assert 'LEGACY RESPONSE' in dispatch.await_args.kwargs['content']
    assert case[0].query(SalesDialogueEvent).filter(SalesDialogueEvent.event_key.like('shadow-draft:%')).count()==1
    slots.assert_not_called()


def test_missing_price_keeps_need_pending_without_hiding_available_material():
    state=DialogueState(tasks=[dict(id='price',topic='pricing',status='completed'),
        dict(id='file',topic='materials',status='pending')])
    results=[ToolResult(operation_id='price',status='partial',data={'property_types':[{'id':'a','property_type':'Studio'}]}),
        ToolResult(operation_id='file',status='success',data={'materials':[{'asset_id':'a','name':'Plans PDF','content_tags':['floor_plan']}],'coverage_confirmed':True})]
    draft=compose(SimpleNamespace(state=state,results=results))
    assert 'prices have not been confirmed' in draft.text
    assert draft.asset_ids==('a',) and 'price' in draft.pending_task_ids
