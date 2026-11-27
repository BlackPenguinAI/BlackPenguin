"""HEI-06 bounded monetary presentation repair; no SDK/provider calls."""
from copy import deepcopy
import pytest

REQUEST = 'Show me the available 3 bedroom houses under $350,000 as a numbered list.'
ROWS = [
    {'id':'van','reference':'van','property_type':'Van Buren','kind':'property_type','price':325000,'currency':'USD','bedrooms':3},
    {'id':'oak','reference':'oak','property_type':'Oakwood','kind':'property_type','price':340000,'currency':'USD','bedrooms':3},
]
COMMERCIAL = {'property_types':[{'id':r['id'],'property_type':r['property_type'],
    'starting_price':r['price'],'currency':r['currency']} for r in ROWS]}
REPLY = 'Homes under $350,000:\n1. Oakwood — $340k\n2. Van Buren — $325k\nWhich option?'


def prepare(reply=REPLY, **kwargs):
    from app.modules.hermes_sales_core.conversation_parity import delivered_property_menu
    rows=deepcopy(ROWS)
    args={'buyer_message':REQUEST,'search_rows':rows,'menus':[delivered_property_menu(reply,rows)],
          'observations':[{'tool':'search_properties','status':'executed','error_code':None}],
          'active_search':{'source_inbound_message_id':'input','criteria':{'bedrooms':3,'max_price_usd':350000}},
          'inbound_id':'input','media_offer':None,'channel':'sms'}
    args.update(kwargs)
    return args


def repair(reply=REPLY, **kwargs):
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_numbered_catalog
    return reconcile_numbered_catalog(reply,**prepare(reply,**kwargs))


@pytest.mark.parametrize('reply', [REPLY,
    'Homes under $350,000:\n1. Oakwood — $340,000\n2. Van Buren — $325,000\nWhich option?',
    '1. Oakwood — $325,000\n2. Van Buren — $340,000\nWhich option?',
    '1. Oakwood — $999,999\n2. Van Buren — $1\nWhich option?'])
def test_repair_rechecks_prices_and_preserves_model_order(reply):
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    from app.modules.hermes_sales_core.bp_operation_receipts import visible_menu
    _,original=validate_monetary_reply(reply,COMMERCIAL)
    assert original['replaced']
    repaired,menu=repair(reply)
    assert '1. Oakwood: starting price USD 340,000; 3 bedrooms' in repaired
    assert '2. Van Buren: starting price USD 325,000; 3 bedrooms' in repaired
    assert '$350,000' not in repaired and '$999,999' not in repaired
    assert [o['unit_id'] for o in menu['options']]==['oak','van']
    assert visible_menu(repaired,menu)
    validated,evidence=validate_monetary_reply(repaired,COMMERCIAL)
    assert validated==repaired and evidence['checked'] and not evidence['replaced']


@pytest.mark.parametrize('change', ['stale','foreign_ref','duplicate_row','missing_search',
    'failed_search','mixed_tools','media_offer','compound_request','non_search','non_property_menu',
    'over_budget','equal_to_strict_budget','wrong_bedrooms','unknown_price','different_currency','unverified_name'])
def test_uncertain_or_mixed_menu_remains_blocked(change):
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_numbered_catalog
    args=prepare()
    if change=='stale':args['active_search']['source_inbound_message_id']='previous'
    if change=='foreign_ref':args['menus'][0]['options'][0]['unit_id']='unapproved'
    if change=='duplicate_row':args['search_rows'].append(deepcopy(ROWS[0]))
    if change=='missing_search':args['observations']=[]
    if change=='failed_search':args['observations'][0]['status']='rejected'
    if change=='mixed_tools':args['observations'].append({'tool':'book_onsite_visit','status':'executed'})
    if change=='media_offer':args['media_offer']={'unit_id':'van'}
    if change=='compound_request':args['buyer_message']=REQUEST+' Also send the brochure.'
    if change=='non_search':args['buyer_message']='Tell me about Van Buren.'
    if change=='non_property_menu':args['menus'].append({'type':'visit_time'})
    if change=='over_budget':args['search_rows'][0]['price']=360000
    if change=='equal_to_strict_budget':args['search_rows'][0]['price']=350000
    if change=='wrong_bedrooms':args['search_rows'][0]['bedrooms']=4
    if change=='unknown_price':args['search_rows'][0]['price']=None
    if change=='different_currency':args['search_rows'][0]['currency']='MXN'
    if change=='unverified_name':args['search_rows'][0]['property_type']='Another house'
    assert reconcile_numbered_catalog(REPLY,**args) is None


def test_repair_is_not_an_authorization_if_current_catalog_disagrees():
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    reply,_=repair()
    changed=deepcopy(COMMERCIAL)
    changed['property_types'][1]['starting_price']=345000
    _,evidence=validate_monetary_reply(reply,changed)
    assert evidence['replaced']


def test_natural_search_without_explicit_numbering_instruction():
    reply,menu=repair(buyer_message='Show me 3 bedroom homes under $350,000.')
    assert 'starting price USD 340,000' in reply
    assert [o['unit_id'] for o in menu['options']]==['oak','van']


@pytest.mark.parametrize('names', [
    ['search_properties','get_project_overview'],
    ['get_project_overview','search_properties'],
    ['search_properties','get_project_overview','search_properties'],
])
def test_overview_read_does_not_invalidate_current_verified_menu(names):
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    obs=[{'tool':name,'status':'executed','error_code':None} for name in names]
    reply, menu=repair(observations=obs)
    assert [o['unit_id'] for o in menu['options']]==['oak','van']
    assert 'starting price USD 340,000' in reply
    assert 'starting price USD 325,000' in reply
    assert validate_monetary_reply(reply,COMMERCIAL)[0]==reply


@pytest.mark.parametrize('obs', [
    [{'tool':'get_project_overview','status':'executed','error_code':None}],
    [{'tool':'search_properties','status':'executed'}, {'tool':'get_project_overview','status':'rejected'}],
    [{'tool':'search_properties','status':'executed'}, {'tool':'get_project_overview','status':'executed','error_code':'UNKNOWN'}],
    [{'tool':'search_properties','status':'executed'}, {'tool':'get_unit_details','status':'executed'}],
    [{'tool':'search_properties','status':'executed'}, {'tool':'update_search_preferences','status':'executed'}],
    [{'tool':'search_properties','status':'executed'}, {'tool':'get_unit_media','status':'executed'}],
    [{'tool':'search_properties','status':'executed'}, None],
])
def test_overview_exception_does_not_authorize_missing_search_or_other_tools(obs):
    assert repair(observations=obs) is None


def direct_args(**updates):
    rows=deepcopy(ROWS)
    for row in rows:
        row.update(availability_verified=True,available_units=2)
    exact={'criteria':{'bedrooms':3,'max_price_usd':350000},'scope':'temporary',
           'match_count':2,'source_inbound_message_id':'input'}
    later={'criteria':{'bedrooms':3,'max_price_usd':330000},'scope':'temporary',
           'match_count':1,'source_inbound_message_id':'input'}
    args={'buyer_message':REQUEST,'search_batches':[{'rows':rows,'search':exact},
          {'rows':rows[:1],'search':later}], 'menus':[],
          'observations':[{'tool':'search_properties','status':'executed','error_code':None}]*2,
          'active_search':deepcopy(later),'inbound_id':'input','media_offer':None,'channel':'sms'}
    args.update(updates)
    return args


def test_exact_direct_search_survives_a_later_speculative_narrow_search():
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_direct_catalog
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    args=direct_args()
    original=deepcopy(args)
    reply,menu,search=reconcile_direct_catalog(REPLY,**args)
    assert args==original
    assert [o['unit_id'] for o in menu['options']]==['oak','van']
    assert search==args['search_batches'][0]['search']
    assert validate_monetary_reply(reply,COMMERCIAL)[0]==reply


@pytest.mark.parametrize('raw',[
    'Homes under $350,000:\n**1.** **Van Buren** — $325k\n**2.** **Oakwood** — $340k',
    'Homes under $350,000:\n1. House: Van Buren — $325k\n2. House: Oakwood — $340k',
    'Homes under $350,000:\n1. Unknown property — $1\n2. Another invented property — $2',
])
def test_unbound_model_menu_is_replaced_not_delivered(raw):
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_direct_catalog
    from app.modules.sales_agent.monetary_policy import validate_monetary_reply
    reply,menu,search=reconcile_direct_catalog(raw,**direct_args())
    assert [o['unit_id'] for o in menu['options']]==['van','oak']
    assert 'Unknown property' not in reply and 'invented' not in reply
    assert validate_monetary_reply(reply,COMMERCIAL)[0]==reply


@pytest.mark.parametrize('mutation', ['no_exact','wrong_epoch_source','state_changed','no_search_observation',
    'missing_observation','rejected_read','operation','mixed_request','unknown_availability','empty_inventory',
    'incomplete','over_budget','wrong_currency','duplicate','unknown_bedrooms','unverified_feature','permanent',
    'other_menu','media_offer','bad_channel','strict_cap'])
def test_direct_list_remains_fail_closed(mutation):
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_direct_catalog
    args=direct_args(); exact=args['search_batches'][0]; rows=exact['rows']
    if mutation=='no_exact':exact['search']['criteria']['max_price_usd']=340000
    if mutation=='wrong_epoch_source':exact['search']['source_inbound_message_id']='old'
    if mutation=='state_changed':args['active_search']['match_count']=2
    if mutation=='no_search_observation':args['observations']=[{'tool':'get_project_overview','status':'executed'}]
    if mutation=='missing_observation':args['observations']=args['observations'][:1]
    if mutation=='rejected_read':args['observations'].append({'tool':'get_project_overview','status':'rejected'})
    if mutation=='operation':args['observations'].append({'tool':'get_unit_media','status':'executed'})
    if mutation=='mixed_request':args['buyer_message']+=' Also send a PDF.'
    if mutation=='unknown_availability':rows[1]['availability_verified']=False
    if mutation=='empty_inventory':rows[1]['available_units']=0
    if mutation=='incomplete':exact['search']['match_count']=21
    if mutation=='over_budget':rows[1]['price']=360000
    if mutation=='wrong_currency':rows[1]['currency']='MXN'
    if mutation=='duplicate':rows[1]['reference']=rows[0]['reference']
    if mutation=='unknown_bedrooms':rows[1]['bedrooms']=None
    if mutation=='unverified_feature':exact['search']['criteria']['private_backyard']=True
    if mutation=='permanent':exact['search']['scope']='permanent'
    if mutation=='other_menu':args['menus']=[{'type':'visit_time'}]
    if mutation=='media_offer':args['media_offer']={'unit_id':'van'}
    if mutation=='bad_channel':args['channel']='simulation'
    if mutation=='strict_cap':rows[1]['price']=350000
    assert reconcile_direct_catalog(REPLY,**args) is None


@pytest.mark.parametrize('criteria', [
    {'bedrooms_min':3,'bedrooms_max':3,'max_price_usd':350000},
    {'bedrooms_any':[3],'relative_price_lt':350000},
    {'bedrooms':3,'bedrooms_min':3,'max_price_usd':350000},
])
def test_semantically_equivalent_exact_searches(criteria):
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_direct_catalog
    args=direct_args();args['search_batches'][0]['search']['criteria']=criteria
    audit={}
    _,menu,search=reconcile_direct_catalog(REPLY,**args,audit=audit)
    assert [o['unit_id'] for o in menu['options']]==['oak','van']
    assert search['criteria']==criteria
    assert audit['reasons']==['no_exact_criteria','canonical_rendered']


def test_direct_repair_diagnostic_does_not_return_row_content():
    from app.modules.hermes_sales_core.numbered_catalog import reconcile_direct_catalog
    args=direct_args();args['search_batches'][0]['rows'][1]['currency']='INVALID_SECRET'
    audit={}
    assert reconcile_direct_catalog(REPLY,**args,audit=audit) is None
    assert audit['reasons']==['no_exact_criteria','row_filter_conflict']
