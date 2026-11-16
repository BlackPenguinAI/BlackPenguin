import pytest
from app.modules.sales_agent.contextual_answers import repair

@pytest.mark.parametrize('text,reply,topic',[
 ('3 bedrooms it’s ok for me','Are 2 bedrooms essential, or would you consider another bedroom count?','catalog'),
 ('3 it’s good for me','Are 2 bedrooms essential, or would you consider another bedroom count?','catalog'),
 ('The layout of the rooms','What matters most to you about Home?','property_details'),
 ('Financing pls','','financing'),('Financing please','','financing')])
def test_current_answer_preserves_quote_and_does_not_create_visit(text,reply,topic):
 fixed,notes=repair({'confidence':0,'requests':[]},text,reply)
 assert notes and fixed['confidence']==0 and fixed['requests'][0]['topic']==topic
 assert fixed['requests'][0]['evidence']==text and fixed['visit'] is None

@pytest.mark.parametrize('text',['No','No, it’s ok','No, bye'])
def test_no_more_questions_is_not_visit_decline(text):
 fixed,notes=repair({'confidence':0,'requests':[]},text,'What else would you like to know before your visit?')
 assert notes and fixed['courtesy']['kind']=='farewell' and fixed['visit'] is None

def test_same_number_needs_current_question():
 raw={'confidence':0,'requests':[]}
 assert repair(raw,'3 it’s good for me','')[1]==[]
 fixed,notes=repair(raw,'Option 3','Which time?',{'appointment_offer':{'options':[1,2,3]}})
 assert notes and fixed['visit']['action']=='select' and fixed['requests'][0]['target']['kind']=='appointment'

def test_complement_offer_acceptance_is_specific_and_not_visit_consent():
    meta={'material_offer':{'items':[{'binding':{'mime_type':'application/pdf','name':'Approved PDF'}}]}}
    for text in ['Ok','Yes','Yes, share me','Send me this pdf']:
        fixed,notes=repair({'confidence':0},text,'Would you like the PDF?',meta)
        assert notes and fixed['visit'] is None and fixed['requests'][0]['target']['expression']=='Approved PDF'
    meta['material_offer']['items'].append({'binding':{'mime_type':'text/html','name':'Gallery'}})
    assert not repair({'confidence':0},'Ok','Would you like materials?',meta)[1]


def test_gallery_acceptance_and_explicit_pdf_selection():
    gallery={'binding':{'mime_type':'image/jpeg','type':'gallery_image','name':'Approved gallery'}}
    pdf={'binding':{'mime_type':'application/pdf','name':'Approved PDF'}}
    for text in ['Yes','Send me the gallery']:
        fixed,notes=repair({'confidence':0},text,'Would you like the gallery?',{'material_offer':{'items':[gallery]}})
        assert notes and fixed['requests'][0]['subject']=='photos' and fixed['visit'] is None
    fixed,notes=repair({'confidence':0},'Send me the pdf','',{'material_offer':{'items':[gallery,pdf]}})
    assert notes and fixed['requests'][0]['target']['expression']=='Approved PDF'


from test_sales_turn_1720 import case,approved_asset
from types import SimpleNamespace as N
from datetime import datetime,timedelta
from app.modules.projects.models import ProjectPropertyType,SalesAssetShare
from app.modules.sales_agent.dialogue_store import Scope
from app.modules.sales_agent.models import OutboundMessage
from app.modules.sales_agent.complementary_material import build
from test_sales_ai_group_b import agent
from test_sales_active_integration import understanding
from app.modules.sales_agent.models import SalesMessage


@pytest.mark.parametrize('text,reply,metadata,topic',[
    ('3 bedrooms it’s ok for me','Are 2 bedrooms essential, or would you consider another bedroom count?',{},'catalog'),
    ('The layout of the rooms','What matters most to you?',{},'property_details'),
    ('Financing pls','',{},'financing'),
    ('Option 3','Which time?',{'appointment_offer':{'options':[1,2,3]}},'appointment'),
    ('Yes','Would you like the PDF?',{'material_offer':{'items':[{'binding':{'mime_type':'application/pdf','name':'Approved PDF'}}]}},'materials'),
])
def test_production_input_compiler_accepts_contextual_repair(text,reply,metadata,topic):
    from app.modules.sales_agent.interpretation_input import compile_input
    import json
    raw=understanding(text,'other').model_dump()
    raw['confidence']=0
    value,notes=compile_input(json.dumps(raw),text,previous_reply=reply,previous_metadata=metadata)
    assert value.requests[0].topic.value==topic and value.confidence==0
    assert any(note.get('action')=='latest_question_contextual_answer' for note in notes)


@pytest.mark.parametrize('previous_status',[None,'queued','sent','delivered','read'])
def test_complement_uses_durable_receipts_and_same_property(case,previous_status):
    db,company,project,lead,conversation=case
    owner=ProjectPropertyType(project=project,name='Synthetic home',review_status='confirmed')
    other=ProjectPropertyType(project=project,name='Another home',review_status='confirmed')
    db.add_all([owner,other]);db.flush()
    pdf=approved_asset(case,['brochure'],name='Approved PDF')
    pdf.property_type_id=owner.id
    unrelated=approved_asset(case,['brochure'],name='Unrelated PDF')
    unrelated.property_type_id=other.id
    db.commit()
    scope=Scope(company.id,project.id,conversation.id,lead.id)
    state=N(selected_property_type_id=owner.id,selected_unit_id=None,constraints=[],property_constraints=[])
    metadata={'material_bindings':[{'binding':{'type':'gallery_image','asset_id':'current-gallery'}}]}
    if previous_status:
        outgoing=OutboundMessage(conversation_id=conversation.id,idempotency_key='synthetic-prior-material',channel=conversation.channel,provider='telnyx',status=previous_status,content='Prior material')
        db.add(outgoing);db.flush()
        db.add(SalesAssetShare(company_id=company.id,project_id=project.id,lead_id=lead.id,source_id=pdf.source_id,sales_asset_id=pdf.id,outbound_message_id=outgoing.id,channel=None,token_hash='synthetic-receipt',expires_at=datetime.utcnow()+timedelta(days=1)))
        db.commit()
    choice=build(db,scope,state,metadata,conversation.channel)
    if previous_status in {'sent','delivered','read'}:assert choice is None
    else:
        assert choice['metadata']['material_offer']['asset_ids']==[pdf.id]
        assert 'floor plan' not in choice['text'].lower()


def test_confirmed_booking_contributes_intent_without_inventing_segment(case):
    from app.modules.sales_crm.models import Meeting,MeetingStatus
    from app.modules.sales_agent.profile_intelligence import update
    db,company,project,lead,conversation=case
    db.add(Meeting(project_id=project.id,lead_id=lead.id,meeting_time=datetime.utcnow()+timedelta(days=1),status=MeetingStatus.CONFIRMED))
    db.commit()
    result=update(db,lead,commercial={'inventory':[],'property_types':[]},message_count=5)
    assert result.factor_breakdown['appointment_intent']==35
    assert result.factor_breakdown['financial_readiness']==0 and lead.assigned_segment is None


def test_real_turn_path_delivers_accepted_complement_without_reasking(agent):
    owner=ProjectPropertyType(project=agent.project,name='Synthetic home',review_status='confirmed')
    agent.db.add(owner);agent.db.commit()
    case_data=(agent.db,agent.company,agent.project,agent.lead,agent.conversation)
    gallery=approved_asset(case_data,['gallery_image'],name='Approved gallery',asset_type='gallery_image')
    pdf=approved_asset(case_data,['brochure'],name='Approved PDF')
    gallery.property_type_id=pdf.property_type_id=owner.id
    agent.db.commit()
    agent.turn('Synthetic home',understanding('Synthetic home','property_details',references=[dict(kind='property',expression='Synthetic home',evidence='Synthetic home')]))
    _,run=agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    assert run.status=='completed',run.output_snapshot
    latest=agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc()).first()
    assert latest.metadata_json['material_offer']['asset_ids']==[pdf.id]
    raw=understanding('Yes','other').model_dump()
    raw['confidence']=0
    import json
    _,run=agent.turn('Yes',json.dumps(raw))
    assert run.status=='completed',run.output_snapshot
    assert {s.sales_asset_id for s in agent.db.query(SalesAssetShare)}=={gallery.id,pdf.id}
    latest=agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc()).first()
    assert not latest.metadata_json.get('material_offer') and latest.metadata_json.get('visit_invitation')
