"""Pure focused contracts for demo turn lifecycle; no model or provider calls."""
from copy import deepcopy
from datetime import timedelta
import pytest

from app.modules.hermes_sales_core import commercial_delivery as d, sales_preferences
from app.modules.hermes_sales_core.choice_state import record_delivered_menu
from app.modules.hermes_sales_core.bp_operation_receipts import visible_menu, recap_visible
from app.modules.sales_agent.monetary_policy import validate_monetary_reply
from test_commercial_delivery import Port, VAN, CEDAR, COMMERCIAL, observed


class LifecyclePort(Port):
    """Small deterministic port double; the actual ORM lane is a separate test."""
    def __init__(self,message):
        super().__init__(message)
        self.domain_observations=[]; self.prepared_visit=None; self.explicit_focus=None
    def invoke(self,name,args,scope):
        if name=='update_search_preferences':
            self.calls.append((name,args,scope))
            return sales_preferences.apply(self.state,sales_preferences.parse_declarations(self.message),source_message_id=self.inbound_id)
        if name=='search_properties':
            self.calls.append((name,args,scope))
            criteria=args['criteria']
            matches=[r for r in self.rows if r['bedrooms']==criteria['bedrooms'] and r['price']<criteria['max_price_usd']]
            self.search(criteria,matches,source=self.inbound_id)
            return {'ok':True,'matching_properties':matches,'match_count':len(matches)}
        return super().invoke(name,args,scope)


@pytest.mark.parametrize('message',[
    'My maximum budget is $350,000. I need exactly 3 bedrooms.',
    'My budget is up to $350,000. I want exactly 3 bedrooms.',
    'I can spend up to $350,000. I require exactly 3 bedrooms.',
])
def test_preference_capture_is_domain_owned_and_idempotent(message):
    p=LifecyclePort(message)
    expected=d.capture_primary(p,{'update_search_preferences'})
    assert expected['budget']['maximum_usd']==350000
    assert expected['bedrooms']['mode']=='exact' and expected['bedrooms']['preferred']==3
    assert expected['last_source_message_id']=='new' and expected['revision']==1
    assert p.domain_observations==[observed('update_search_preferences')]
    # Hermes may search without invoking the preference tool, or repeat it.
    p.invoke('search_properties',{'criteria':{'bedrooms':3,'max_price_usd':350000}},'scope')
    assert p.state['search_preferences']==expected
    assert d.capture_primary(p,{'update_search_preferences'})==expected
    assert p.state['search_preferences']['revision']==1


def test_capture_requires_enabled_tool_and_native_result():
    p=LifecyclePort('My maximum budget is $350,000. I need exactly 3 bedrooms.')
    assert d.capture_primary(p,set()) is None and not p.calls
    p.invoke=lambda *_: {'ok':True}  # a misleading success cannot prove the draft
    assert d.capture_primary(p,{'update_search_preferences'}) is None
    assert not p.primary_captured


@pytest.mark.parametrize('message',[
    'Show me 6 bedroom houses under $100,000.',
    'Find 6 bedroom properties below $100,000.',
    'Which houses with 6 bedrooms are under $100,000?',
])
def test_first_search_and_no_match_do_not_depend_on_monetary_failure(message):
    p=LifecyclePort(message)
    prior=deepcopy(p.state['search_preferences'])
    wrong={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
    assert d.strict_search_bounds(message,wrong)==wrong
    assert d.explicit_search_filters(message)=={'bedrooms':6,'max_price_usd':100000}
    assert p.state['search_preferences']==prior
    # Even if Hermes omits the search altogether, use the native read once.
    assert d.ensure_search(p,[],{'search_properties'})
    assert d.ensure_search(p,[],{'search_properties'})
    assert len(p.calls)==1
    reply=d.search_reply(p,[],'sms',model_reply='I can help you explore homes.')
    assert 'no verified matches' in reply and '100,000' not in reply
    assert p.state['search_preferences']==prior and p.state['active_search']['match_count']==0
    assert validate_monetary_reply(reply,COMMERCIAL,lead_profile={})[0]==reply
    assert validate_monetary_reply('Van Buren costs USD 100,000.',COMMERCIAL,lead_profile={})[1]['replaced']


@pytest.mark.parametrize('message',[
    'Show me 4 bedroom houses under $400,000.',
    'Find 4 bedroom homes below $400,000 just for comparison.',
    'Which properties with 4 bedrooms are under $400,000?',
])
def test_temporary_search_preserves_primary_even_if_model_uses_old_filters(message):
    p=LifecyclePort('My maximum budget is $350,000. I need exactly 3 bedrooms.')
    prior=d.capture_primary(p,{'update_search_preferences'})
    p.message=message; p.inbound_id='next'; p.domain_observations=[]
    old={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
    assert d.strict_search_bounds(message,old)==old
    p.search(old['criteria'],[VAN],source=p.inbound_id)
    assert d.ensure_search(p,[observed('search_properties')],{'search_properties'})
    assert p.state['search_preferences']==prior
    reply=d.search_reply(p,[observed('search_properties')],'sms',model_reply='No matches.')
    assert 'Cedar Grove' in reply and '375,000' in reply
    assert p.state['active_search']['source_inbound_message_id']=='next'
    assert p.state['active_search']['match_count']==1
    # Preserve a naturally generated correct single-result answer.
    assert d.search_reply(p,[observed('search_properties')],'sms',model_reply='Cedar Grove has 4 bedrooms.') is None


@pytest.mark.parametrize('message',[
    'Show me 4 bedroom houses under $400,000 with pool.',
    'Find 4 bedroom homes below $400,000 and send me the PDF.',
    'Show me 4 bedroom houses under $400,000 in a different city.',
])
def test_recovery_never_drops_unaccounted_for_qualifiers(message):
    p=LifecyclePort(message)
    assert d.explicit_search_filters(message) is None
    assert not d.ensure_search(p,[],{'search_properties'}) and not p.calls


def test_search_recovery_does_not_bypass_denials_or_other_goals():
    p=LifecyclePort('Find 6 bedroom properties below $100,000.')
    for obs in ([observed('search_properties','rejected','GLOBAL_TOOL_DISABLED')],
                [observed('search_properties','rejected','COMMERCIAL_POLICY_HOLD')],
                [observed('book_onsite_visit')]):
        assert not d.ensure_search(p,obs,{'search_properties'})
    assert not d.ensure_search(p,[],set()) and not p.calls


def bind_visit_choice(p, kind, *, stale=False, mismatched=False):
    dates=['2026-11-29','2026-11-30']; day=dates[-1]
    p.add_slots(dates if kind=='visit_day' else [day],exact=kind=='visit_time',period='' if kind=='visit_day' else day)
    offer=p.state['last_slot_search']
    offer['expires_at']=(p.now+timedelta(minutes=-1 if stale else 10)).isoformat()
    offer['source_reply_message_id']='accepted-reply'
    p.prior_visit_offer=deepcopy(offer); p.prior_visit_draft=deepcopy(p.state['visit_draft'])
    # Use the exact same domain menu constructor used by the live adapter.
    from app.modules.hermes_sales_core.contextual_choices import choice_from_slots
    menu=choice_from_slots(p.slot_batches[-1]['result']);menu.update(display_name='Van Buren',proposal_id=offer['proposal_id'])
    saved=record_delivered_menu(p.state,menu=menu,outbound_message_id='other-reply' if mismatched else 'accepted-reply')
    p.choice={'type':kind,'status':'resolved','unit_id':VAN['id'],'menu':saved,'choice':saved['options'][1]}
    p.slot_batches=[]
    return saved


def test_commercial_label_survives_menu_receipt_and_next_turn_proof():
    p=LifecyclePort('Option 2');menu=bind_visit_choice(p,'visit_day')
    reply='Available days to visit Van Buren (America/Mexico_City):\n'+ '\n'.join(f'{x["index"]}. {x["label"]}' for x in menu['options'])
    assert menu['display_name']=='Van Buren' and menu['unit_id']==VAN['id']
    assert visible_menu(reply,menu)
    assert not visible_menu(reply.replace('Van Buren','Oakwood'),menu)
    assert menu['source_reply_message_id']=='accepted-reply'


def test_prepared_day_is_read_only_and_wrong_time_tool_is_rejected():
    p=LifecyclePort('Option 2');bind_visit_choice(p,'visit_day')
    pre=d.prepare_visit_choice(p,{'get_available_visit_slots','select_visit_time'})
    assert pre['kind']=='visit_day' and pre['args']=={'date_str':'2026-11-30'}
    assert p.calls==[('get_available_visit_slots',{'date_str':'2026-11-30'},'scope')]
    rejected=d.replay_visit_choice(p,'select_visit_time',{})
    assert rejected['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
    assert d.replay_visit_choice(p,'get_available_visit_slots',{'date_str':'2026-11-30'})==pre['result']
    assert d.replay_visit_choice(p,'get_available_visit_slots',{'date_str':'2026-11-29'})['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
    reply=d.visit_reply(p,[observed('select_visit_time','rejected',rejected['error_code'])],{'get_available_visit_slots','select_visit_time'})
    assert 'Van Buren' in reply and p.menus[0]['type']=='visit_time' and visible_menu(reply,p.menus[0])
    assert not p.state.get('confirmation_request') and len(p.calls)==1
    assert not p.state['last_slot_search']['source_reply_message_id']


def test_prepared_hour_only_creates_draft_and_is_not_repeated():
    p=LifecyclePort('The second option');bind_visit_choice(p,'visit_time')
    pre=d.prepare_visit_choice(p,{'select_visit_time','get_available_visit_slots'})
    assert pre['kind']=='visit_time' and pre['args']['start_time']=='11:00'
    snapshot=deepcopy(p.state)
    assert d.replay_visit_choice(p,'select_visit_time',pre['args'])==pre['result']
    assert d.replay_visit_choice(p,'get_available_visit_slots',{})['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
    assert p.state==snapshot and len(p.calls)==1
    reply=d.visit_reply(p,[observed('get_available_visit_slots','rejected','VISIT_SELECTION_ALREADY_RESOLVED')],{'select_visit_time','get_available_visit_slots'})
    req=p.state['confirmation_request']
    assert req['status']=='recap_required' and recap_visible(reply,req) and 'not booked yet' in reply
    assert not req.get('confirmed_inbound_message_id') and len(p.calls)==1
    assert d.replay_visit_choice(p,'book_onsite_visit',{}) is None  # never intercept effect tools


@pytest.mark.parametrize('stale,mismatch,enabled,message',[
    (True,False,{'select_visit_time'},'Option 2'),
    (False,True,{'select_visit_time'},'Option 2'),
    (False,False,set(),'Option 2'),
    (False,False,{'select_visit_time'},'I do not want the second option'),
])
def test_stale_foreign_denied_or_negated_choice_is_not_prepared(stale,mismatch,enabled,message):
    p=LifecyclePort(message);bind_visit_choice(p,'visit_time',stale=stale,mismatched=mismatch)
    assert d.prepare_visit_choice(p,enabled) is None and not p.calls and not p.state.get('confirmation_request')


def test_broad_visit_request_with_options_is_not_catalog_search():
    p=LifecyclePort('What days are available to visit Van Buren? Please list the options.')
    reply=d.visit_reply(p,[],{'get_available_visit_slots'})
    assert 'Van Buren' in reply and p.menus[0]['type']=='visit_day'
    assert p.calls==[('get_available_visit_slots',{'date_str':'upcoming days'},'scope')]
    assert not d.broad_visit_request('Compare Van Buren and Oakwood and visit the second.')


def test_exclusive_price_filter_preserves_displayed_cap():
    request='Show me 3 bedroom houses under $350,000.'
    args={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
    assert d.strict_search_bounds(request,args)['criteria']=={**args['criteria'],'relative_price_lt':350000}
    assert d.strict_search_bounds(request.replace('under','up to'),args)==args
    compound={**args,'criteria':{**args['criteria'],'min_bathrooms':2}}
    assert d.strict_search_bounds(request,compound)==compound


def test_independent_queries_preserve_narrower_cap_and_recover_exact_request():
    p=LifecyclePort('Show me the available 3 bedroom houses under $350,000 as a numbered list.')
    exact={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
    narrower={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':310000}}
    p.invoke('search_properties',d.strict_search_bounds(p.message,exact),'scope')
    first=deepcopy(p.search_batches[-1]);assert first['search']['match_count']==2
    independent=d.strict_search_bounds(p.message,narrower)
    assert independent==narrower
    p.invoke('search_properties',independent,'scope')
    assert p.search_batches[-1]['search']['match_count']==1
    assert p.search_batches[0]==first
    assert d.ensure_search(p,[observed('search_properties')]*2,{'search_properties'})
    assert p.state['active_search']['match_count']==2
    assert p.search_batches[1]['search']['criteria']['max_price_usd']==310000
    assert p.state['search_preferences']['revision']==0


@pytest.mark.parametrize('profile',[{}, {'facts':{'budget_maximum':{'value':350000}}}])
def test_recovered_no_match_passes_both_monetary_boundaries(profile):
    p=LifecyclePort('Find 6 bedroom homes below $100,000.')
    original=deepcopy(profile)
    assert d.ensure_search(p,[],{'search_properties'})
    reply=d.search_reply(p,[],'sms',model_reply='I can help.')
    prepared,evidence=validate_monetary_reply(reply,COMMERCIAL,lead_profile=profile)
    dispatched,backstop=validate_monetary_reply(prepared,COMMERCIAL,lead_profile=profile)
    assert reply==prepared==dispatched and not evidence.get('replaced') and not backstop.get('replaced')
    assert profile==original and 'within your stated budget' in reply
    assert validate_monetary_reply('Van Buren costs USD 100,000.',COMMERCIAL,lead_profile=profile)[1]['replaced']


def test_new_primary_ack_passes_dispatch_before_crm_write():
    p=LifecyclePort('My maximum budget is $350,000. I need exactly 3 bedrooms.')
    assert d.capture_primary(p,{'update_search_preferences'})
    reply=d.primary_ack(p,[])
    assert 'stated budget limit' in reply and 'exactly 3 bedrooms' in reply
    for _ in range(2):
        checked,evidence=validate_monetary_reply(reply,COMMERCIAL,lead_profile={})
        assert checked==reply and not evidence.get('replaced')
