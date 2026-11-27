"""Regression contracts. No live provider, credentials or model calls.

The existing 18 real-SDK and 31 offline assertions remain unchanged. These
focused tests cover the new domain presentation boundary and negative cases.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from app.modules.hermes_sales_core import commercial_delivery as d
from app.modules.hermes_sales_core import sales_preferences
from app.modules.hermes_sales_core.bp_operation_receipts import recap_visible, visible_menu
from app.modules.sales_agent.monetary_policy import validate_monetary_reply


def observed(tool, status='executed', error_code=None):
    return {'tool':tool,'status':status,'error_code':error_code}


def home(ref, name, price, beds, baths):
    return {'id':ref,'reference':ref,'property_type':name,'kind':'property_type',
            'price':price,'currency':'USD','bedrooms':beds,'bathrooms':baths,
            'availability_verified':True,'available_units':1}


VAN=home('van-id','Van Buren',300000,3,1)
OAK=home('oak-id','Oakwood',320000,3,2)
CEDAR=home('cedar-id','Cedar Grove',375000,4,3)
COMMERCIAL={'property_types':[{'id':r['id'],'property_type':r['property_type'],
              'starting_price':r['price'],'currency':'USD'} for r in (VAN,OAK,CEDAR)]}


class Port:
    def __init__(self,message):
        self.message=message;self.inbound_id='new';self.now=datetime(2026,11,27,tzinfo=timezone.utc)
        self.state={'lead':{},'search_preferences':sales_preferences.empty(),
                    'conversation_focus':{'property_type_id':VAN['id']},'active_search':None}
        self.menus=[];self.offered_media=None;self.search_batches=[];self.slot_batches=[]
        self.comparison_rows=[];self.comparison_batches=[];self.choice=None;self.primary_captured=False
        self.rows=[VAN,OAK,CEDAR];self.calls=[];self.snapshot=SimpleNamespace(scope='scope')
        self.prior_visit_offer=None;self.prior_visit_draft=None
    def _all_rows(self): return self.rows
    def _resolve(self,ref): return next((r for r in self.rows if r['reference']==ref),None)
    def search(self,criteria,rows,scope='temporary',source='new',count=None):
        search={'criteria':criteria,'scope':scope,'match_count':len(rows) if count is None else count,
                'source_inbound_message_id':source}
        self.state['active_search']=deepcopy(search)
        self.search_batches.append({'search':search,'rows':deepcopy(rows)})
    def add_slots(self, dates, *, exact=False, source='new', period='', proposal='proposal', times=('10:00','11:00')):
        opts=[{'date':day,'start_time':clock,'starts_at_utc':f'{day}T{clock}:00+00:00'}
              for day in dates for clock in times]
        offer={'unit_id':VAN['id'],'proposal_id':proposal,'source_inbound_message_id':source,
               'source_reply_message_id':None,'options':opts,'timezone':'America/Mexico_City'}
        result={'ok':True,'unit_id':VAN['id'],'proposal_id':proposal,'timezone':offer['timezone']}
        if exact:
            result.update(date=dates[0],available_slots=[{'date':x['date'],'start_time':x['start_time']} for x in opts])
        else: result['available_dates']=[{'date':x} for x in dates]
        draft={'unit_id':VAN['id'],'status':'hour_needed' if exact else 'day_needed'}
        self.state['last_slot_search']=deepcopy(offer);self.state['visit_draft']=deepcopy(draft)
        self.slot_batches.append({'result':result,'offer':offer,'draft':draft,'args':{'date_str':period}})
    def invoke(self,name,args,scope):
        self.calls.append((name,args,scope))
        if name=='get_available_visit_slots':
            if args['date_str']=='upcoming days': self.add_slots(['2026-11-29','2026-11-30'],period='upcoming days')
            else: self.add_slots([args['date_str']],exact=True,period=args['date_str'])
        if name=='select_visit_time':
            prior=self.state['last_slot_search']
            if prior.get('source_reply_message_id') and args['proposal_id']==prior['proposal_id']:
                self.state['confirmation_request']={'kind':'book','status':'recap_required','selected_inbound_message_id':'new',
                    'unit_id':prior['unit_id'],'proposal_id':prior['proposal_id'],'date':args['date_str'],'start_time':args['start_time'],
                    'timezone':prior['timezone'],'visit_address':'123 Main Street'}
        return {'ok':True}


@pytest.mark.parametrize('message',[
    'My maximum budget is $350,000. I need exactly 3 bedrooms.',
    'My budget is up to $350,000. I want exactly 3 bedrooms.',
    'I can spend up to $350,000. I require exactly 3 bedrooms.',
])
def test_primary_declarations_are_explicit_and_idempotent(message):
    p=Port(message);changes=d.primary_declaration(message,p.state)
    assert changes['budget']['maximum_usd']==350000 and changes['bedrooms']['preferred']==3
    assert sales_preferences.apply(p.state,changes,source_message_id='new')['ok']
    saved=deepcopy(p.state['search_preferences']);sales_preferences.apply(p.state,changes,source_message_id='new')
    assert p.state['search_preferences']==saved and saved['revision']==1
    p.primary_captured=True
    reply=d.primary_ack(p,[observed('update_search_preferences')])
    assert 'stated budget limit' in reply and 'exactly 3 bedrooms' in reply
    assert '350,000' not in reply
    assert validate_monetary_reply(reply,COMMERCIAL,lead_profile={})[0]==reply


@pytest.mark.parametrize('message',[
    'Show me 4 bedroom houses under $400,000.', 'If I can spend $400,000, I need exactly 4 bedrooms.',
    'My budget is up to 350,000 MXN.', 'My budget is up to $350,000?',
    'For comparison, I need exactly 4 bedrooms.',
])
def test_no_automatic_preference_revision(message):
    assert not d.primary_declaration(message,{'search_preferences':{'revision':1}})


def test_temporary_criteria_do_not_mutate_primary():
    p=Port('Show me 4 bedroom houses under $400,000.');p.state['search_preferences']['revision']=1
    p.state['search_preferences']['budget']['maximum_usd']=350000
    before=deepcopy(p.state);args={'scope':'temporary','criteria':{'bedrooms':3,'max_price_usd':350000}}
    # Independent agent read remains independent, and no preference is changed.
    assert d.strict_search_bounds(p.message,args)==args and p.state==before
    assert d.explicit_search_filters(p.message)=={'bedrooms':4,'max_price_usd':400000}
    other={'scope':'temporary','criteria':{'min_bathrooms':3}}
    assert d.strict_search_bounds(p.message,other)==other


@pytest.mark.parametrize('message',[
    'Show me 6 bedroom houses under $100,000.',
    'Find 6 bedroom properties below $100,000.',
    'Which houses with 6 bedrooms are under $100,000?',
])
def test_no_match_budget_evidence_does_not_become_listing_price(message):
    p=Port(message);p.search({'bedrooms':6,'max_price_usd':100000},[])
    obs=[observed('search_properties')];before=deepcopy(p.state['search_preferences'])
    reply=d.search_reply(p,obs,'sms',monetary_rejected=True)
    assert 'no verified matches' in reply and 'within your stated budget' in reply and p.menus==[]
    assert '100,000' not in reply
    original={'facts':{'budget_maximum':{'value':999}}}
    assert p.state['search_preferences']==before
    # Preparation and dispatch both see the real persisted profile.
    checked,evidence=validate_monetary_reply(reply,COMMERCIAL,lead_profile=original)
    assert checked==reply and not evidence['replaced']
    for fake in ('Van Buren costs USD 100,000.','Your budget is USD 200,000.'):
        assert validate_monetary_reply(fake,COMMERCIAL,lead_profile=original)[1]['replaced']
    assert original=={'facts':{'budget_maximum':{'value':999}}}


@pytest.mark.parametrize('source,count,criteria',[
    ('old',0,{'bedrooms':6,'max_price_usd':100000}),
    ('new',3,{'bedrooms':6,'max_price_usd':100000}),
    ('new',0,{'bedrooms':3,'max_price_usd':100000}),
])
def test_incomplete_or_wrong_search_cannot_supply_budget_evidence(source,count,criteria):
    p=Port('Find 6 bedroom homes below $100,000.');p.search(criteria,[],source=source,count=count)
    obs=[observed('search_properties')]
    assert d.search_reply(p,obs,'sms',monetary_rejected=True) is None
    assert d.search_reply(p,obs,'sms',monetary_rejected=False) is None


def test_temporary_single_result_is_approved_and_not_a_preference_change():
    p=Port('Show me 4 bedroom houses under $400,000.');p.search({'bedrooms':4,'max_price_usd':400000},[CEDAR])
    prefs=deepcopy(p.state['search_preferences']);obs=[observed('search_properties')]
    reply=d.search_reply(p,obs,'sms',monetary_rejected=True)
    assert 'Cedar Grove' in reply and '375,000' in reply and p.state['search_preferences']==prefs
    assert validate_monetary_reply(reply,COMMERCIAL)[0]==reply
    assert d.search_reply(p,obs+[observed('book_onsite_visit')],'sms',monetary_rejected=True) is None
    assert d.search_reply(p,obs+[observed('search_properties','rejected','COMMERCIAL_POLICY_HOLD')],'sms',monetary_rejected=True) is None


def test_comparison_uses_actual_scoped_distinct_facts():
    p=Port('Compare Van Buren and Oakwood. How many bathrooms does each have?')
    p.comparison_rows=[VAN,OAK];p.comparison_batches=[[VAN,OAK]]
    reply=d.compare_reply(p,[observed('compare_properties')]);assert 'Van Buren: 1 bathroom.' in reply
    assert 'Oakwood: 2 bathrooms.' in reply and 'Oakwood has more bathrooms.' in reply
    p.comparison_batches=[[VAN,CEDAR]]
    assert d.compare_reply(p,[observed('compare_properties')]) is None
    p.comparison_batches=[[VAN,OAK]];p.message='Compare Van Buren and Oakwood: bathrooms and prices.'
    assert d.compare_reply(p,[observed('compare_properties')]) is None


def test_broad_visit_keeps_verified_menu_and_project_timezone():
    p=Port('What days are available to visit Van Buren?');p.add_slots(['2026-11-29','2026-11-30'])
    p.add_slots(['2026-11-29'],exact=True,period='2026-11-29',proposal='narrow')
    reply=d.visit_reply(p,[observed('get_available_visit_slots')],{'get_available_visit_slots'})
    assert 'Van Buren' in reply and 'America/Mexico_City' in reply and 'van-id' not in reply
    menu=p.menus[0];assert menu['type']=='visit_day' and menu['proposal_id']=='proposal'
    assert p.state['last_slot_search']['proposal_id']=='proposal' and visible_menu(reply,menu)
    assert p.state['last_slot_search']['source_reply_message_id'] is None
    assert not visible_menu(reply.replace('Van Buren','Oakwood'),menu)


def test_broad_visit_recovers_only_native_availability_read():
    p=Port('What days are available to visit Van Buren?');p.add_slots(['2026-11-29'],exact=True,period='2026-11-29')
    obs=[observed('get_available_visit_slots')]
    assert d.visit_reply(p,obs,{'get_available_visit_slots'})
    assert p.calls==[('get_available_visit_slots',{'date_str':'upcoming days'},'scope')]
    assert not p.state.get('confirmation_request')


def test_typed_day_selects_exact_dates_not_model_guessed_days():
    p=Port('Option 2');p.choice={'type':'visit_day','status':'resolved','unit_id':VAN['id'],'choice':{'date':'2026-11-30'}}
    reply=d.visit_reply(p,[],{'get_available_visit_slots'})
    assert p.calls==[('get_available_visit_slots',{'date_str':'2026-11-30'},'scope')]
    assert p.menus[0]['date']=='2026-11-30' and visible_menu(reply,p.menus[0])


def test_typed_time_can_only_draft_recap_not_book():
    p=Port('Option 2');p.add_slots(['2026-11-30'],exact=True,period='2026-11-30')
    p.state['last_slot_search']['source_reply_message_id']='delivered';p.prior_visit_offer=deepcopy(p.state['last_slot_search'])
    p.prior_visit_draft=deepcopy(p.state['visit_draft'])
    p.choice={'type':'visit_time','status':'resolved','unit_id':VAN['id'],
              'choice':{'date':'2026-11-30','start_time':'11:00','proposal_id':'proposal'}}
    p.add_slots(['2026-11-29'],exact=True,period='2026-11-29',proposal='speculative')
    reply=d.visit_reply(p,[observed('get_available_visit_slots')],{'select_visit_time','get_available_visit_slots'})
    req=p.state['confirmation_request'];assert req['status']=='recap_required' and req['proposal_id']=='proposal'
    assert recap_visible(reply,req) and 'not booked yet' in reply and '123 Main Street' in reply
    assert not recap_visible(reply.replace('Van Buren','Oakwood'),req)
    assert not recap_visible(reply.replace('11:00','10:00'),req)
    assert [c[0] for c in p.calls]==['select_visit_time']


def test_denied_or_unrelated_tools_do_not_recover():
    p=Port('What days are available to visit Van Buren?');p.add_slots(['2026-11-29','2026-11-30'])
    assert d.visit_reply(p,[observed('get_available_visit_slots','rejected','COMMERCIAL_POLICY_HOLD')],{'get_available_visit_slots'}) is None
    assert d.visit_reply(p,[observed('get_available_visit_slots')],set()) is None
    assert d.visit_reply(p,[observed('get_available_visit_slots'),observed('book_onsite_visit')],{'get_available_visit_slots'}) is None
    p.rows.append(home('duplicate','Van Buren',250000,2,1))
    assert d.visit_reply(p,[observed('get_available_visit_slots')],{'get_available_visit_slots'}) is None
    assert not p.calls
