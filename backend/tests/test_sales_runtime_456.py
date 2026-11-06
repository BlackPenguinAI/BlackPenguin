"""Staged runtime regressions; no live model or business side effects."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from unittest.mock import patch
from test_sales_turn_1720 import case, outbound, approved_asset
from app.core.config import settings
from app.modules.sales_agent.dialogue_store import Scope, save, load, DialogueConflict
from app.modules.sales_agent.understanding_contract import DialogueState, Understanding, Reference
from app.modules.sales_agent.dialogue_tasks import prepare_tasks, resolve_reference
from app.modules.sales_agent.dialogue_tools import ReadTools, ToolCall
from app.modules.sales_agent.dialogue_orchestrator import run_turn
from app.modules.sales_agent.models import SalesMessage, OutboundMessage
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
from app.modules.projects.models import ProjectPropertyType, SalesAssetShare
from app.modules.sales_crm.models import Meeting


CASES=json.loads((Path(__file__).parent/'fixtures/sales_understanding_cases.json').read_text())['cases']


def scope(case):
    _,c,p,l,v=case
    return Scope(c.id,p.id,v.id,l.id)


def inbound(case, payload=None):
    db,_,_,_,v=case
    payload=payload or CASES[0]
    message=SalesMessage(conversation_id=v.id, channel='sms', direction='inbound',role='user', content=payload['inbound'])
    db.add(message);db.commit()
    return message, Understanding.model_validate(payload['model_output'])


def execute(case,monkeypatch,payload=None,**kwargs):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    message,u=inbound(case,payload)
    return run_turn(case[0],scope(case),message_id=message.id,understanding=u,expected_revision=kwargs.pop('expected_revision',0),event_key=kwargs.pop('event_key','turn'),**kwargs)


def test_disabled_runtime_never_reads_db(monkeypatch):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',False)
    with pytest.raises(PermissionError):
        run_turn(None,None,message_id='x',understanding={},expected_revision=0,event_key='x')


@pytest.mark.parametrize('scenario',CASES,ids=lambda c:c['id'])
def test_all_scripted_cases_remain_non_effecting(case,monkeypatch,scenario):
    result=execute(case,monkeypatch,scenario,max_steps=30)
    db=case[0]
    assert result.revision==1
    assert db.query(Meeting).count()==db.query(OutboundMessage).count()==db.query(SalesAssetShare).count()==0
    assert not case[-1].is_paused
    assert db.query(SalesMessage).filter_by(direction='outbound').count()==0
    assert db.query(SalesDialogueEvent).one().payload_json['metadata']['external_actions']==0


def test_partial_material_and_financing_are_both_processed(case,monkeypatch):
    db,c,p,l,v=case
    approved_asset(case,['brochure','floor_plan'])
    p.profile.profile_data={'payment_methods':['Bank financing']}
    p.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};db.commit()
    result=execute(case,monkeypatch)
    assert len(result.results)==2 and all(r.status=='success' for r in result.results)
    assert 'Bank financing' in str(result.results)
    assert db.query(SalesAssetShare).count()==0


def test_or_falls_back_after_empty_and_cancels_unused_alternatives(case,monkeypatch):
    scenario=next(c for c in CASES if c['id']=='or')
    # Photos can have a brochure fallback, so a floor-plan only file cannot satisfy photos.
    approved_asset(case,['floor_plan'])
    result=execute(case,monkeypatch,scenario)
    assert len(result.results)==2 and all(r.status=='empty' for r in result.results)
    case[0].rollback()
    approved_asset(case,['photos'])
    result=execute(case,monkeypatch,scenario,event_key='with-photo')
    assert len(result.results)==1
    assert sorted(t.status for t in result.state.tasks)==['cancelled','pending']


def test_persistent_restrictions_survive_new_understanding(case,monkeypatch):
    db=case[0]
    state=DialogueState(constraints=[{'topic':'materials','subject':'brochure','scope':'until_explicit_change','evidence':'No brochures'}])
    save(db,scope(case),event_key='prior',expected_revision=0,state=state);db.commit()
    result=execute(case,monkeypatch,expected_revision=1)
    assert result.results[0].status=='denied'
    assert result.state.constraints==state.constraints


def test_reference_uses_offer_order_not_catalog_sort(case):
    db,c,p,l,v=case
    a=ProjectPropertyType(project=p,name='Studio',review_status='confirmed',sort_order=0)
    b=ProjectPropertyType(project=p,name='Loft',review_status='confirmed',sort_order=1)
    db.add_all([a,b]);db.commit()
    sent=outbound(db,v,'1. Loft 2. Studio')
    state=DialogueState(offers=[{'kind':'property','message_id':sent.id,'option_ids':[b.id,a.id]}])
    a.sort_order=10;b.sort_order=0;db.commit()
    ref=Reference(kind='property',expression='2',evidence='2')
    assert resolve_reference(db,scope(case),state,ref)['id']==a.id
    state.offers[0].expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert resolve_reference(db,scope(case),state,ref) is None
    assert resolve_reference(db,scope(case),state,Reference(kind='property',expression='Loft',evidence='Loft'))['id']==b.id


def test_ambiguous_simultaneous_offer_requires_clarification(case):
    db,c,p,l,v=case;sent=outbound(db,v,'Which option?')
    state=DialogueState(offers=[{'kind':'property','message_id':sent.id,'option_ids':['a']},
        {'kind':'appointment','message_id':sent.id,'option_ids':['b']}])
    assert resolve_reference(db,scope(case),state,Reference(kind='ambiguous',expression='1',evidence='1')) is None


def test_tool_argument_conflict_and_revocation_revalidation(case):
    asset=approved_asset(case,['brochure'])
    message,u=inbound(case)
    state=prepare_tasks(DialogueState(),u,message.id);task=state.tasks[0]
    gateway=ReadTools(case[0],scope(case))
    call=ToolCall(operation_id='once',task_id=task.id,topic='materials',subject='brochure')
    assert gateway.execute(call,state).status=='success'
    asset.approval_status='draft';case[0].commit()
    assert gateway.execute(call,state).status=='empty'
    with pytest.raises(DialogueConflict):
        gateway.execute(call.model_copy(update={'property_id':'foreign'}),state)


def test_turn_retry_returns_saved_outcome_and_changed_input_conflicts(case,monkeypatch):
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    message,u=inbound(case)
    args=dict(message_id=message.id,understanding=u,expected_revision=0,event_key='same')
    first=run_turn(case[0],scope(case),**args);case[0].commit()
    assert run_turn(case[0],scope(case),**args)==first
    assert case[0].query(SalesDialogueEvent).count()==1
    with pytest.raises(DialogueConflict):
        run_turn(case[0],scope(case),**{**args,'max_steps':2})


@pytest.mark.parametrize('max_steps,max_seconds',[(0,5),(31,5),(True,5),(8,0),(8,float('nan')),(8,True)])
def test_limits_reject_invalid_parameters(case,monkeypatch,max_steps,max_seconds):
    with pytest.raises(ValueError):execute(case,monkeypatch,max_steps=max_steps,max_seconds=max_seconds)


def test_limits_preserve_pending_needs_and_rollback_preserves_history(case,monkeypatch):
    result=execute(case,monkeypatch,max_steps=1)
    assert result.stop_reason=='step_limit' and any(t.status=='pending' for t in result.state.tasks)
    case[0].rollback()
    assert load(case[0],scope(case))[0]==0


def test_time_limit_stops_without_tool_calls(case,monkeypatch):
    ticks=iter([0,10])
    result=execute(case,monkeypatch,clock=lambda:next(ticks))
    assert result.stop_reason=='time_limit' and not result.results


def test_old_task_preserved_and_new_ids_are_message_scoped(case):
    message,u=inbound(case)
    old=DialogueState(tasks=[{'id':'old','topic':'financing','status':'suspended'}])
    first=prepare_tasks(old,u,message.id)
    assert first.tasks[0].id=='old'
    assert prepare_tasks(first,u,message.id)==first
    second=prepare_tasks(first,u,'another-message')
    assert len(second.tasks)==5


def test_clarification_holds_interrupted_tasks(case,monkeypatch):
    scenario=next(c for c in CASES if c['model_output']['requires_clarification'])
    state=DialogueState(tasks=[{'id':'interrupted','topic':'financing','status':'suspended'}])
    save(case[0],scope(case),event_key='old',expected_revision=0,state=state);case[0].commit()
    result=execute(case,monkeypatch,scenario,expected_revision=1)
    assert not result.results and result.stop_reason=='clarification'
    assert result.state.tasks[0].status=='suspended'


def test_files_are_not_marked_delivered_by_lookup(case,monkeypatch):
    approved_asset(case,['brochure'])
    result=execute(case,monkeypatch)
    material=next(t for t in result.state.tasks if t.topic.value=='materials')
    assert material.status=='pending'
    assert result.results[0].data['delivery']=='not_sent'


def test_fallback_photos_is_partial_not_fabricated_coverage(case):
    approved_asset(case,['brochure'])
    scenario=next(c for c in CASES if c['id']=='or')
    message,u=inbound(case,scenario);state=prepare_tasks(DialogueState(),u,message.id)
    task=state.tasks[0]
    result=ReadTools(case[0],scope(case)).execute(ToolCall(operation_id='photo',task_id=task.id,topic=task.topic,subject=task.subject),state)
    assert result.status=='partial' and not result.data['coverage_confirmed']


def test_dependency_blocks_without_dropping_task(case,monkeypatch):
    state=DialogueState(tasks=[{'id':'a','topic':'appointment','status':'awaiting_user'},
        {'id':'b','topic':'financing','status':'pending','depends_on':['a']}])
    save(case[0],scope(case),event_key='old',expected_revision=0,state=state);case[0].commit()
    result=execute(case,monkeypatch,expected_revision=1)
    assert next(t for t in result.state.tasks if t.id=='b').status=='pending'


def test_tool_denies_forged_subject_or_foreign_selection(case):
    message,u=inbound(case);state=prepare_tasks(DialogueState(),u,message.id);task=state.tasks[0]
    gateway=ReadTools(case[0],scope(case))
    assert gateway.execute(ToolCall(operation_id='bad',task_id=task.id,topic='materials',subject='photos'),state).status=='denied'
    assert gateway.execute(ToolCall(operation_id='foreign',task_id=task.id,topic='materials',subject='brochure',property_id='foreign'),state).status=='revoked'


def test_new_modules_are_not_referenced_by_live_worker():
    root=Path(__file__).parents[1]/'app/modules/sales_agent'
    for file in ['graph.py','live_worker.py','live_service.py','router.py','service.py']:
        content=(root/file).read_text()
        assert 'dialogue_orchestrator' not in content and 'dialogue_tools' not in content


def test_approved_gallery_tag_confirms_photo_content(case):
    approved_asset(case,['gallery_image'])
    scenario=next(c for c in CASES if c['id']=='or')
    message,u=inbound(case,scenario);state=prepare_tasks(DialogueState(),u,message.id);task=state.tasks[0]
    result=ReadTools(case[0],scope(case)).execute(ToolCall(operation_id='gallery',task_id=task.id,topic=task.topic,subject=task.subject),state)
    assert result.status=='success' and result.data['coverage_confirmed']


def test_delivery_conflict_is_not_a_confirmed_date(case):
    state=DialogueState(tasks=[{'id':'delivery','topic':'delivery','status':'pending'}])
    context={'property_types':[], 'confirmed_project_facts':{'delivery_dates':'2027'},
             'data_conflicts':[{'code':'ready_status_future_delivery'}]}
    with patch('app.modules.sales_agent.dialogue_tools.build_commercial_context',return_value=context):
        result=ReadTools(case[0],scope(case)).execute(ToolCall(operation_id='delivery',task_id='delivery',topic='delivery'),state)
    assert result.status=='conflict' and not result.data


def test_or_prefers_definite_brochure_over_unverified_photo_fallback(case,monkeypatch):
    approved_asset(case,['brochure'])
    scenario=next(c for c in CASES if c['id']=='or')
    result=execute(case,monkeypatch,scenario)
    assert [r.status for r in result.results]==['partial','success']
    assert next(t for t in result.state.tasks if t.subject=='photos').status=='cancelled'
    assert next(t for t in result.state.tasks if t.subject=='brochure').status=='pending'


def test_diagnostic_retry_with_tour_query_is_identical_and_not_delivery_capability(case,monkeypatch):
    approved_asset(case,['virtual_tour'],links=[{'url':'https://example.com/show/?m=example','kind':'virtual_tour','label':'Tour'}])
    scenario=next(c for c in CASES if any(r.get('subject')=='virtual_tour' for r in c['model_output']['requests']))
    monkeypatch.setattr(settings,'SALES_DIALOGUE_RUNTIME_ENABLED',True)
    message,u=inbound(case,scenario)
    args=dict(message_id=message.id,understanding=u,expected_revision=0,event_key='tour')
    first=run_turn(case[0],scope(case),**args);case[0].commit()
    assert run_turn(case[0],scope(case),**args)==first
    assert 'm=example' not in str(first.results)
