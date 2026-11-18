"""P3-A: regression gates for real lead property focus (no external network)."""
from types import SimpleNamespace as NS

from app.modules.sales_agent.live_property_continuity import decision
from app.modules.sales_agent.property_reply_anchor import anchor, material_scope_ok

IDS = ['property-madison', 'property-cleveland', 'property-van-buren', 'property-augusta']
NAMES = dict(zip(IDS, ('Madison','Cleveland','Van Buren','Augusta')))
VISIBLE = ('Here are the 3-bedroom options in this project:\n\n'
           '1. Madison — 3 bedrooms.\n\n'
           '2. Cleveland — 3 bedrooms.\n\n'
           '3. Van Buren — 3 bedrooms.\n\n'
           '4. Augusta — 3 bedrooms.\n\n'
           'Which option would you like to explore?')
META = {'property_catalog_offer':{'property_type_ids': IDS}}


def test_second_option_is_cleveland_from_the_last_visible_catalog():
    for utterance in ('Second option','The second option','the second one','Option 2','2','The second option of the list'):
        assert decision(utterance,META,IDS,NAMES,VISIBLE)==('select',IDS[1])
    assert decision('Third option',META,IDS,NAMES,VISIBLE)==('select',IDS[2])
    assert decision('Fourth option',META,IDS,NAMES,VISIBLE)==('select',IDS[3])



def test_punctuated_legacy_catalog_survives_language_hold():
    # A language-hold response must not replace the last accepted catalog.
    # Older naturalized rows can end with a full stop: '2. Loft.'.
    old_ids=['property-studio','property-loft']
    old_names=dict(zip(old_ids, ('Studio','Loft')))
    old_meta={'property_catalog_offer':{'property_type_ids':old_ids}}
    rendered=('Here are the property options I can confirm:\n\n'
              '1. Studio.\n\n2. Loft.\n\n'
              'Which property option would you like to explore?')
    assert decision('2',old_meta,old_ids,old_names,rendered)==('select',old_ids[1])
    assert decision('the second one',old_meta,old_ids,old_names,rendered)==('select',old_ids[1])
    assert decision('2',old_meta,old_ids,old_names,rendered.replace('2. Loft.', '2. Studio.'))==('clarify',None)
    assert decision('Second option',old_meta,old_ids,old_names,rendered.replace('2. Loft.', '2. Unapproved.'))==('clarify',None)


def test_ordinal_does_not_bind_unknown_or_reordered_catalog():
    assert decision('Second option',META,IDS,NAMES,VISIBLE.replace('2. Cleveland','2. Madison'))==('clarify',None)
    assert decision('Second option',META,list(reversed(IDS)),NAMES,VISIBLE)==('clarify',None)
    assert decision('Second option',META,IDS,{**NAMES,IDS[1]:'Other'},VISIBLE)==('clarify',None)
    assert decision('Second option',META,IDS,NAMES,'Here are some options')==('clarify',None)
    assert decision('Option 5',META,IDS,NAMES,VISIBLE)==('clarify',None)
    assert decision('Second option',META,IDS[:2],NAMES,VISIBLE)==('clarify',None)
    assert decision('Second option',{},IDS,NAMES,VISIBLE) is None


def test_ordinal_cannot_take_over_booking_material_or_qualification_offer():
    for field in ('appointment_offer','material_offer','qualification_offer',
                  'booking_confirmation','control_confirmation','location_offer'):
        assert decision('Second option',{**META,field:True},IDS,NAMES,VISIBLE) is None
    for text in ('2 bedrooms','2 AM','I want the second appointment',
                 'Second option and confirm a visit','Send the second brochure'):
        assert decision(text,META,IDS,NAMES,VISIBLE) is None


def test_reply_names_approved_selected_property_without_claiming_new_facts():
    products=[{'id':ID,'property_type':name} for ID,name in NAMES.items()]
    original='Here is the approved brochure: https://example.test/brochure'
    text,audit=anchor(original,IDS[1],products,topics=['materials'],material_shared=True)
    assert text=='Cleveland\n\n'+original
    assert audit['property_id']==IDS[1] and audit['action']=='prepend_verified_property_name'
    reply='Here are the details for Cleveland: 3 bedrooms.'
    assert anchor(reply,IDS[1],products,topics=['property_details'])[0]==reply
    assert anchor('Hi!',IDS[1],products,topics=['other'])[0]=='Hi!'
    assert anchor(original,'unknown-id',products,topics=['materials'])[0]==original
    assert anchor(original,None,products,topics=['materials'])[0]==original
    assert anchor(original,IDS[1],products,topics=['catalog'],property_catalog=True)[0]==original
    assert anchor('Visit options available.',IDS[1],products,booking_answer=True)[0].startswith('Cleveland\n\n')


def test_material_delivery_fails_closed_on_unbound_or_cross_property_tasks():
    chosen=NS(property_id=IDS[1])
    previous=NS(property_id=IDS[0])
    unknown=NS(property_id=None)
    assert material_scope_ok([chosen],IDS[1])
    assert not material_scope_ok([previous],IDS[1])
    assert not material_scope_ok([unknown],IDS[1])
    assert not material_scope_ok([chosen,previous],IDS[1])
    assert material_scope_ok([],IDS[1])
    assert material_scope_ok([previous],None)


def test_preview_generates_bounded_intent_without_authorizing_material_or_booking(monkeypatch):
    from app.modules.sales_agent import live_property_continuity, first_booking, dialogue_store
    from app.modules.sales_agent.understanding_contract import DialogueState, Offer
    previous=NS(id='outbound-1',content=VISIBLE,
                metadata_json={'property_catalog_offer':{'property_type_ids':IDS}})
    monkeypatch.setattr(first_booking,'accepted_outbound',lambda *a,**kw:previous)
    class Query:
        def filter(self,*args,**kw):return self
        def all(self):return [NS(id=identifier,name=NAMES[identifier]) for identifier in IDS]
    db=NS(query=lambda *args,**kw:Query())
    state=DialogueState(offers=[Offer(kind='property',message_id=previous.id,option_ids=IDS)])
    saved=[]
    def save(db,scope,**kw):
        saved.append(kw)
        return 8,kw['state']
    monkeypatch.setattr(dialogue_store,'save',save)
    result=live_property_continuity.try_preview(db,NS(project_id='project'),NS(),
        NS(id='inbound-1',content='Second option'),state=state,
        previous_meta=previous.metadata_json,expected_revision=7,
        event_key='active-understanding:inbound-1')
    assert result.status=='accepted'
    u=result.state.last_understanding
    assert u.selected_reference_id=='p3a_choice'
    assert u.references[0].expression=='option 2'
    assert u.requests[0].topic.value=='property_details'
    assert all(r.topic.value!='appointment' for r in u.requests)
    assert not u.visit and not u.requires_clarification
    assert saved[0]['metadata']['selected_property_id']==IDS[1]
    assert saved[0]['metadata']['effect_authorization'] is False
    assert state.last_understanding is None
    assert state.selected_property_type_id is None  # selection belongs to planner
