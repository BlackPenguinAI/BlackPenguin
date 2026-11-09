"""Currency placement and non-monetary quantity regression matrix."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.modules.sales_agent.monetary_policy import validate_monetary_reply
from app.modules.sales_agent.live_service import _dispatch
from app.modules.sales_agent.models import AgentRun, SalesConversation, OutboundMessage
from app.modules.sales_crm.models import Lead
from test_onboarding_revisions_and_money import context

FACTS={'property_types':[{'id':'a','property_type':'Residence A','starting_price':30,'maximum_price':45.75,'currency':'USD'}]}


@pytest.mark.parametrize('text',[
    'Residence A prices range from 30 USD to 30000.',
    'Residence A: 30 USD–30000.',
    'Residence A cuesta entre 30 dólares y 30000.',
    'Residence A: 30 dollars through 30000.',
    'Residence A: 30 dólares hasta 30000.',
    'Residence A: 30 USD a 30000.',
    'Residence A: 30 USD—30000.',
    'Residence A: 30 USD-30000.',
    'Residence A: 30 USD to 30,000.00.',
    'Residence A: 30 USD to 30000 and 2 bedrooms.',
    'Residence A: 30–45.75 USD to 30000.',
    'Residence A: 45.75 USD to 30.',
    'Residence A: 30 USD to -45.75.',
    'Residence A: 30 USD to 45.75 EUR.',
    'Residence A: 30 dollars to 45.75 Canadian dollars.',
    'Residence A: 30 USD and 2 USD bedrooms.',
])
def test_invalid_range_bounds_are_never_silently_ignored(text):
    reply,evidence=validate_monetary_reply(text,FACTS)
    assert evidence['checked'] and evidence['replaced']
    assert evidence['original_reply']==text and reply!=text


@pytest.mark.parametrize('text',[
    'Residence A: 30 USD to 45.75.',
    'Residence A: 30 USD–45.75.',
    'Residence A: 30 dollars through 45.75.',
    'Residence A: entre 30 dólares y 45.75.',
    'Residence A: 30 dólares hasta 45.75.',
    'Residence A: 30 USD to 45.75 USD.',
    'Residence A: $30–45.75.',
    'Residence A: 30–45.75 USD.',
    'Residence A: USD 30–45.75.',
    'Residence A: USD 30–45.75 USD.',
    'Residence A: 30 USD to 45.75 and 2 bedrooms.',
    'Residence A: 30–45.75 USD and 2 bedrooms.',
])
def test_approved_ranges_survive_with_currency_in_each_supported_position(text):
    assert validate_monetary_reply(text,FACTS)[0]==text


@pytest.mark.parametrize('quantity',[
    '2 bedrooms','2 bathrooms','2 full bathrooms','2 beds','2 baths',
    '2 dormitorios','2 recámaras','2 habitaciones','2 baños','2 ambientes',
    '60 m²','60 m2','60 square meters','600 square feet','600 sq ft','600 sqft',
    '2 parking spaces','2 plazas','2 cajones','4 floors','4 pisos',
    '2 units','2 homes','2 departamentos','2 unidades',
    '12 months','12 meses','2 years','2 años','14 days','14 días',
    '30 minutes','30 minutos','20%','20 percent',
])
def test_feature_quantities_after_price_are_not_monetary_bounds(quantity):
    text=f'Residence A: USD 30 and {quantity}.'
    reply,evidence=validate_monetary_reply(text,FACTS)
    assert reply==text and not evidence['replaced']


@pytest.mark.parametrize('text',[
    'Residence A: 30 USD and 2 bedrooms.',
    'Residence A: 30 dólares y 2 dormitorios.',
    'Residence A has 2 bedrooms and costs 30 USD.',
    'Residence A: USD 30 and 2 bedrooms. Brochure: https://example.test/brochure.pdf',
])
def test_legitimate_copy_and_document_links_are_not_replaced(text):
    assert validate_monetary_reply(text,FACTS)[0]==text


def test_ignoring_a_bedroom_count_does_not_hide_a_later_invalid_price():
    text='Residence A: USD 30 and 2 bedrooms; the final price is USD 30000.'
    assert validate_monetary_reply(text,FACTS)[1]['replaced']


def test_implicit_range_cannot_use_another_named_propertys_price():
    facts={'property_types':[
        {'id':'a','property_type':'Residence A','starting_price':30,'currency':'USD'},
        {'id':'b','property_type':'Residence B','starting_price':30000,'currency':'USD'},
    ]}
    assert validate_monetary_reply('Residence A: 30 USD to 30000.',facts)[1]['replaced']


def test_known_budget_range_still_is_not_a_project_price_claim():
    profile={'facts':{'budget':{'value':{'minimum':100000,'maximum':200000,'currency':'USD'}}}}
    text='Your budget is 100000 USD to 200000. Which layout do you prefer?'
    assert validate_monetary_reply(text,FACTS,lead_profile=profile)[0]==text


@pytest.mark.parametrize('text,should_replace',[
    ('Residence A prices range from 30 USD to 30000.',True),
    ('Residence A: 30 USD–30000.',True),
    ('Residence A cuesta entre 30 dólares y 30000.',True),
    ('Residence A: USD 30 and 2 bedrooms.',False),
    ('Residence A: USD 30 and 2 bedrooms. Brochure: https://example.test/brochure.pdf',False),
])
def test_actual_dispatch_uses_corrected_price_but_preserves_valid_features(context,text,should_replace):
    db,company,user,project,profile,item=context
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Range regression',phone='+12025550111',consent_status='granted')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,provider='telnyx',channel='sms',is_paused=False)
    db.add(conversation);db.flush()
    run=AgentRun(conversation_id=conversation.id,event_id='range-regression',mode='live',status='completed',graph_version='test',toolset_version='test',prompt_snapshot={},model='test',input_snapshot={},output_snapshot={'reply':text})
    db.add(run);db.commit()
    provider=AsyncMock(return_value={'sid':'test-only-message','status':'sent'})
    with patch('app.modules.sales_agent.live_service.send_sms',provider),patch('app.modules.sales_agent.live_service.send_message',provider):
        message=asyncio.run(_dispatch(db,conversation=conversation,lead=lead,content=text,role='assistant',agent_run_id=run.id))
    assert (message.content!=text)==should_replace
    assert message.content==provider.call_args.kwargs['body']==run.output_snapshot['reply']==db.query(OutboundMessage).one().content
    assert message.metadata_json['monetary_validation']['replaced']==should_replace
