"""Validate the expanded assertions with a separate deterministic SDK double.

This is not model quality evidence. Every domain tool and HTTP receipt is real;
only the model and provider network are replaced inside the existing fixture.
"""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog
from staging_transport import loopback_server, attach_http_worker, check_environment
from staging_scenarios import CASES, CASE_IDS, VARIANTS, CHECKPOINTS, exercise

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')

@pytest.mark.parametrize('family,variant', CASES, ids=CASE_IDS)
def test_staging_harness(real_lane, monkeypatch, tmp_path, family, variant):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.contextual_choices import choice_from_slots, render_menu
    check_environment()
    lane=real_lane;seed_catalog(lane,monkeypatch,tmp_path)
    messages=VARIANTS[family][variant]
    def fake(runtime, request):
        port=runtime._port; observations=[]
        def invoke(name,args):
            result=port.invoke(name,args,request.scope)
            assert result.get('ok'), result
            observations.append({'tool':name,'status':'executed','error_code':None})
            return result
        text=request.message
        step=messages.index(text) if text in messages else -1
        if family=='focus-media':
            if step in (0,1):
                prop=request.verified_context['focused_property']
                field='bathrooms' if step==0 else 'bedrooms'
                reply=f"{prop['display_name']} has {prop[field]} {field}."
            else:
                invoke('get_unit_media',{'unit_id':'van'});reply='I found the requested brochure for Van Buren.'
        elif family=='ordinal':
            if step==0:
                invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}})
                reply='1. Van Buren — USD 325,000\n2. Oakwood — USD 340,000\nWhich would you like to explore?'
            else:
                prop=request.verified_context['focused_property'];reply=f"{prop['display_name']} has {prop['bathrooms']} bathrooms."
        elif family=='temporary':
            if step==0:
                invoke('update_search_preferences',{'budget_mode':'cap','budget_maximum_usd':350000,'bedrooms_mode':'exact','bedrooms_preferred':3})
                reply='I have noted your main preferences.'
            else:
                r=invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':4,'max_price_usd':400000}})
                assert r['match_count']==1
                reply='Cedar Grove has 4 bedrooms and a starting price of USD 375,000.'
        elif family=='no-match':
            r=invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':6,'max_price_usd':100000}})
            assert r['match_count']==0;reply='No verified matches. Would you like to adjust the criteria?'
        elif family=='comparison':
            invoke('compare_properties',{'unit_ids':['van','oak']});reply='Van Buren has 1 bathroom. Oakwood has 2 bathrooms, so Oakwood has more.'
        elif family=='visit':
            choice=request.verified_context.get('resolved_visible_choice') or {}
            if text==messages[0] or choice.get('type')=='visit_day':
                args={'date_str':choice['choice']['date']} if choice.get('type')=='visit_day' else {}
                outcome=invoke('get_available_visit_slots',args)
                menu=choice_from_slots(outcome);assert menu and len(menu['options'])==2
                reply=render_menu(menu).replace('visit van','visit Van Buren (van)').replace('for van','for Van Buren (van)')
            elif choice.get('type')=='visit_time':
                selected=choice['choice'];offer=port.state['last_slot_search']
                invoke('select_visit_time',{'proposal_id':offer['proposal_id'],'date_str':selected['date'],'start_time':selected['start_time']})
                c=port.state['confirmation_request'];reply=f"Please confirm Van Buren (van) on {c['date']} at {c['start_time']} ({c['timezone']}), {c['visit_address']}?"
            else:
                c=port.state['confirmation_request']
                invoke('book_onsite_visit',{'proposal_id':c['proposal_id'],'date_str':c['date'],'start_time':c['start_time'],'unit_id':'van',
                    'first_name':'Test','last_name':'Buyer','email':'buyer@example.invalid','phone':'+15550000001'})
                reply='I will check whether the visit can be confirmed.'
        else:raise AssertionError('Unexpected scenario')
        return TurnResult(reply,[],observations)
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake)
    checkpoints=[]
    with loopback_server(lane.sdk_service.app) as origin:
        attach_http_worker(lane,monkeypatch,origin)
        exercise(lane,family,variant,checkpoints.append)
    assert set(checkpoints)<=CHECKPOINTS and checkpoints[-1]=='complete'
