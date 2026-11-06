"""Regression coverage for the five findings from the pre-integration audit."""
import pytest
from test_sales_turn_1720 import case, model_turn, approved_asset, execute_material
from app.modules.sales_agent.turn_context import appointment_execution_allowed
from app.modules.projects.models import SalesAssetShare
from copy import deepcopy
from app.modules.sales_agent.dialogue_composer import compose
from app.modules.projects.models import ProjectPropertyType
from test_sales_runtime_456 import execute, CASES


def test_live_negation_must_veto_inconsistent_model_appointment_label(case):
    result,_=model_turn(case,"Send photos and explain financing. I don't want an in-person visit yet.",
        primary='request_visual_material',secondary=['request_appointment','request_financing'],
        reply='Here is the information.',confidence=.99)
    assert not appointment_execution_allowed(result), 'Current explicit refusal did not veto a conflicting secondary appointment label.'


def test_live_explicit_photo_exclusion_must_not_share_photo_asset(case):
    brochure=approved_asset(case,['brochure'],name='Approved brochure')
    photo=approved_asset(case,['gallery_image'],name='Separate photo',asset_type='gallery_image')
    (reply,actions,shares),offer=execute_material(case,'Please send the brochure, but do not send photos.',
        result={'primary_intent':'request_document','intent_entities':{'requested_materials':['brochure']}})
    ids={s.sales_asset_id for s in case[0].query(SalesAssetShare).all()}
    assert brochure.id in ids
    assert photo.id not in ids, 'A separate photo was shared despite the explicit photo exclusion.'


def test_live_or_is_not_unconditional_delivery_of_both_alternatives(case):
    approved_asset(case,['brochure'],name='Approved brochure')
    approved_asset(case,['gallery_image'],name='Separate photo',asset_type='gallery_image')
    execute_material(case,'Please send photos or a brochure.')
    ids={s.sales_asset_id for s in case[0].query(SalesAssetShare).all()}
    assert len(ids)==1, 'The OR choice became delivery of both branches.'


def test_new_runtime_ambiguous_material_reference_requires_clarification(case,monkeypatch):
    approved_asset(case,['floor_plan'],name='General plans')
    scenario=deepcopy(CASES[0])
    scenario['inbound']='Send plans for the second option.'
    scenario['model_output']['requests']=[{'id':'a','topic':'materials','subject':'floor_plan','polarity':'request','evidence':'Send plans'}]
    scenario['model_output']['all_of']=['a']
    scenario['model_output']['references']=[{'kind':'ambiguous','expression':'the second option','evidence':'the second option'}]
    result=execute(case,monkeypatch,scenario)
    assert not any(r.data.get('materials') for r in result.results), 'Unresolved reference still retrieved unqualified material.'
    assert any(t.status=='awaiting_user' for t in result.state.tasks)


def test_new_runtime_pending_price_must_remain_pending_in_persistent_task(case,monkeypatch):
    case[0].add(ProjectPropertyType(project=case[2],name='Studio without price',review_status='confirmed'))
    case[0].commit()
    scenario=deepcopy(CASES[0])
    scenario['inbound']='Prices?'
    scenario['model_output']['requests']=[{'id':'a','topic':'pricing','subject':None,'polarity':'request','evidence':'Prices'}]
    scenario['model_output']['all_of']=['a']
    result=execute(case,monkeypatch,scenario)
    draft=compose(result)
    assert draft.pending_task_ids
    task=result.state.tasks[0]
    assert task.status!='completed', 'Draft says price is pending but persistent request task is completed.'
