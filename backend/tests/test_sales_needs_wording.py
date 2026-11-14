"""Commercial wording and scoped acceptance of the optional unknown-home list."""
from datetime import datetime,timedelta
import pytest
from test_sales_turn_1720 import case
from app.modules.sales_agent.needs_search import search,answer,closing,unknown_options,normalize
from app.modules.sales_agent.models import SalesMessage
from app.modules.sales_agent.dialogue_store import Scope
from test_sales_active_integration import understanding


def result(rows):
    text='I need a 2 bedroom home.'
    u,_=normalize(understanding(text,'catalog'),text,{'property_types':[]})
    return search(u,rows,{'exhaustive':False})


def test_matching_home_has_no_warning_about_the_other_homes():
    r=result([{'id':'match','property_type':'Cedar Loft','bedrooms':2,'available_units':1,'inventory_updated_at':'2026-11-13'}, {'id':'unknown','property_type':'Other Home','bedrooms':None}])
    text=answer(r)
    assert 'Cedar Loft' in text and 'Other Home' not in text
    assert not any(word in text.lower() for word in ('catalog','incomplete','missing','other options','bedroom details'))
    assert 'Cedar Loft' in closing(r)


def test_only_relevant_missing_details_are_explained_and_listing_is_optional():
    r=result([{'id':'p','property_type':'Unknown Home','bedrooms':None}])
    assert 'bedroom details' in answer(r) and 'Unknown Home' not in answer(r)
    assert closing(r)=='Would you like to see those homes?'
    assert 'catalog' not in answer(r)


def test_partial_catalog_without_missing_bedrooms_does_not_invent_missing_details():
    r=result([{'id':'p','property_type':'Three Bedroom','bedrooms':3}])
    assert '2-bedroom' in answer(r)
    assert not any(word in answer(r).lower() for word in ('missing','incomplete','bedroom details','no homes exist'))


def test_unavailable_home_is_not_described_as_a_database_quantity():
    r=result([{'id':'p','property_type':'Two Bedroom','bedrooms':2,'available_units':0}])
    assert 'listed as unavailable' in answer(r)
    assert 'quantity' not in answer(r) and 'zero' not in answer(r)


@pytest.mark.parametrize('status,allowed',[('sent',True),('queued',False),('failed',False)])
def test_unknown_home_list_requires_an_accepted_immediate_offer(case,status,allowed):
    db,company,project,lead,conversation=case
    scope=Scope(company.id,project.id,conversation.id,lead.id)
    db.add(SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='Would you like to see those homes?',status=status,metadata_json={'needs_unknown_offer':{'bedrooms':2,'property_ids':['p']}}));db.commit()
    rows=[{'id':'p','property_type':'Unknown Home','bedrooms':None}, {'id':'foreign','property_type':'Unrequested','bedrooms':2}]
    r=unknown_options(db,scope,'Yes',rows)
    assert bool(r)==allowed
    if allowed:
        assert 'Unknown Home' in answer(r) and 'Unrequested' not in answer(r)
        assert 'bedroom details are not available' in answer(r)
        assert r['matching_property_ids']==[]
    assert unknown_options(db,scope,'No, thank you.',rows) is None


def test_interrupted_or_incomplete_offer_is_not_accepted(case):
    db,company,project,lead,conversation=case;scope=Scope(company.id,project.id,conversation.id,lead.id)
    now=datetime.utcnow()
    final=SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='Would you like to see those homes?',status='sent',created_at=now,metadata_json={'needs_unknown_offer':{'bedrooms':2,'property_ids':['p']},'delivery_group':{'key':'offer','total':2,'part':2}})
    db.add(final);db.commit();rows=[{'id':'p','property_type':'Unknown Home','bedrooms':None}]
    assert unknown_options(db,scope,'Yes',rows) is None
    db.add(SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='First part',status='sent',created_at=now-timedelta(seconds=1),metadata_json={'delivery_group':{'key':'offer','total':2,'part':1}}));db.commit()
    assert unknown_options(db,scope,'Yes',rows)
    assert unknown_options(db,scope,'Yes',[])['unknown_options']==[]
    db.add(SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='What is your budget?',status='sent',created_at=now+timedelta(seconds=1)));db.commit()
    assert unknown_options(db,scope,'Yes',rows) is None
