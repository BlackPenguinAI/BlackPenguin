"""The same acceptance assertions, with intentionally imperfect SDK replies.

Actual private HTTP, real isolated BP ORM/domain and accepted provider-double
receipts. Only inference and external providers are simulated. Not proof of
real SDK/model quality. The original 18 scenarios remain untouched.
"""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog
from staging_transport import loopback_server, attach_http_worker, check_environment
from staging_scenarios import VARIANTS, exercise

pytestmark=pytest.mark.usefixtures('hei06_lane_engine')
CASES=[(family,i) for family in ('temporary','no-match','visit') for i in range(3)]


@pytest.mark.parametrize('family,variant',CASES,ids=[f'{f}-{i+1}' for f,i in CASES])
def test_lifecycle_imperfect_sdk(real_lane,monkeypatch,tmp_path,family,variant):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    check_environment();lane=real_lane;seed_catalog(lane,monkeypatch,tmp_path)
    messages=VARIANTS[family][variant]
    def fake(runtime,request):
        port=runtime._port;observations=[];context=request.verified_context
        def invoke(name,args):
            result=port.invoke(name,args,request.scope)
            observations.append({'tool':name,'status':'executed' if result.get('ok') else 'rejected',
                                 'error_code':result.get('error_code')})
            return result
        if family=='temporary':
            if request.message==messages[0]:
                # Real model traces searched instead of explicitly updating the
                # profile. The domain capture must already have happened.
                assert context['primary_preferences']['budget']['maximum_usd']==350000
                assert context['primary_preferences']['bedrooms']['mode']=='exact'
                if variant!=1:
                    invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}})
                reply='Your budget is USD 999,999.' if variant==2 else 'I can help with matching homes.'
            else:
                # Stale primary filters or omission, not the correct request.
                if variant!=1:invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}})
                reply='No matches.'
        elif family=='no-match':
            if variant==0:invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}})
            elif variant==1:invoke('search_properties',{'scope':'temporary','criteria':{'bedrooms':6,'max_price_usd':100000}})
            # Third variant omits the tool; none of these texts triggers the
            # monetary guard, which used to be required for repair.
            reply='I can help you explore the catalog.'
        elif family=='visit':
            choice=context.get('resolved_visible_choice') or {}
            if request.message==messages[0]:
                if variant==0:invoke('get_available_visit_slots',{'date_str':'today'})
                elif variant==1:invoke('get_available_visit_slots',{})
                # Third variant omits tool; initial explicit day request.
                reply='Van Buren may have some options. Which works for you?'
            elif choice.get('type')=='visit_day':
                assert context['verified_visit_selection']['type']=='visit_day'
                # The failure observed in the real run: treating day 2 as an hour.
                rejected=invoke('select_visit_time',{'proposal_id':'wrong','date_str':choice['choice']['date'],'start_time':'11:00'})
                assert rejected['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
                if variant==2:assert invoke('get_available_visit_slots',{'date_str':choice['choice']['date']})['ok']
                reply='1. 10:00 AM\n2. 11:00 AM'
            elif choice.get('type')=='visit_time':
                assert context['verified_visit_selection']['type']=='visit_time'
                selected=choice['choice']
                rejected=invoke('get_available_visit_slots',{})
                assert rejected['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
                if variant==2:
                    assert invoke('select_visit_time',{'proposal_id':selected['proposal_id'],'date_str':selected['date'],'start_time':selected['start_time']})['ok']
                reply='Your visit is confirmed.'  # domain must render recap, not premature success
            else:
                # Real booking remains owned by the existing authorized tool,
                # separate affirmative inbound and native receipt executor.
                c=context['confirmation_request']
                assert c['status']=='awaiting_confirmation'
                assert invoke('book_onsite_visit',{'proposal_id':c['proposal_id'],'date_str':c['date'],'start_time':c['start_time'],'unit_id':c['unit_id'],
                    'first_name':'Test','last_name':'Buyer','email':'buyer@example.invalid','phone':'+15550000001'})['ok']
                reply='I will check whether the visit can be confirmed.'
        else:raise AssertionError('Unexpected scenario')
        return TurnResult(reply,[],observations)
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake)
    checkpoints=[]
    with loopback_server(lane.sdk_service.app) as origin:
        attach_http_worker(lane,monkeypatch,origin)
        exercise(lane,family,variant,checkpoints.append)
    assert checkpoints[-1]=='complete'
