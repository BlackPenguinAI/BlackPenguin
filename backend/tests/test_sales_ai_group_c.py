"""Group C contracts, real inbound integration and compatible visit migration."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import uuid

import pytest
from sqlalchemy import create_engine,inspect,text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_sales_turn_1720 import case,outbound
from test_sales_active_integration import understanding
from test_sales_ai_group_b import agent
from app.modules.sales_agent.lead_profile import resolve,capture,qualification,known
from app.modules.sales_agent.turn_memory import build,propose,proposal_context,booking_digest,remember
from app.modules.sales_agent.appointment_context import AppointmentReadTool,bind_visit
from app.modules.sales_agent.dialogue_store import load,save,Scope,DialogueConflict
from app.modules.sales_agent.understanding_contract import Understanding,DialogueState,ChangeProposal
from app.modules.sales_agent.models import SalesMessage,AgentRun
from app.modules.sales_crm.models import Lead,Meeting,MeetingStatus
from app.modules.projects.models import Project,ProjectPropertyType,ProjectUnit
from app.modules.companies.models import Company
from app.core.config import settings

NOW=datetime(2030,1,1,12,tzinfo=timezone.utc)


def inbound(agent,content):
    row=SalesMessage(conversation_id=agent.conversation.id,channel=agent.conversation.channel,
        direction='inbound',role='user',content=content,status='received')
    agent.db.add(row);agent.db.commit();return row


def pref(agent,field,evidence,*,value='UNTRUSTED normalized model value'):
    row=inbound(agent,evidence)
    u=understanding(evidence)
    u=u.model_copy(update={'preferences':[{'key':field,'value':value,'evidence':evidence}]})
    u=Understanding.model_validate(u.model_dump())
    capture(agent.db,agent.scope,u,row.id);agent.db.commit()
    return row


def product(agent,name='Studio'):
    row=ProjectPropertyType(project=agent.project,name=name,review_status='confirmed')
    agent.db.add(row);agent.db.commit();return row


def meeting(agent,*,starts=None,status=MeetingStatus.CONFIRMED,project=None,lead=None,product_id=None):
    project=project or agent.project;lead=lead or agent.lead
    row=Meeting(project_id=project.id,lead_id=lead.id,meeting_time=(starts or NOW+timedelta(days=1)).replace(tzinfo=None),
        status=status,visit_address='100 Main Street',visit_location_label='Showroom',location_confirmation_status='confirmed')
    agent.db.add(row);agent.db.flush()
    if product_id:bind_visit(agent.db,row,company_id=agent.company.id,property_type_id=product_id)
    agent.db.commit();return row


def proposal(row,**changes):
    return ChangeProposal(id='proposal-1',kind='reschedule',meeting_id=row.id,booking_sha256=booking_digest(row),
        expires_at=NOW+timedelta(minutes=20),starts_at=NOW+timedelta(days=3),**changes)


@pytest.mark.parametrize('shape',['flat','graph','source_answers','legacy_facts'])
def test_meta_budget_shapes_preserve_source_value_and_do_not_reask(agent,shape):
    value='250000 USD'
    if shape=='flat':agent.lead.meta_form_data={'budget':value,'form_id':'synthetic-form'}
    elif shape=='graph':agent.lead.meta_form_data={'field_data':[{'name':'budget','values':[value]}]}
    elif shape=='source_answers':agent.lead.lead_profile_data={'source_answers':[{'key':'budget','value':value,'source':'meta_form'}]}
    else:agent.lead.lead_profile_data={'facts':{'budget':{'value':value,'source':'meta_form','confirmed':True}}}
    agent.db.commit()
    result=resolve(agent.lead)
    assert result['current']['budget']['value']==value
    assert result['current']['budget']['status']=='declared'
    assert qualification(agent.lead,{'qualification_rules':'budget, financing'})[1]=='financing'


@pytest.mark.parametrize('field',['age','gender','religion','race','nationality','email','phone_number','api_key','access_token'])
def test_unmapped_personal_and_secret_form_fields_never_enter_profile(agent,field):
    agent.lead.meta_form_data={field:'PRIVATE_SENTINEL','budget':'200000 USD'}
    serialized=json.dumps(resolve(agent.lead))
    assert 'PRIVATE_SENTINEL' not in serialized and field not in resolve(agent.lead)['current']


def test_resolver_is_read_only_and_distinguishes_unknown_declared_confirmed(agent):
    agent.lead.meta_form_data={'budget':'200000 USD','bedrooms':'unknown'}
    agent.lead.lead_profile_data={'facts':{'financing':{'value':'Pre-approval recorded','source':'staff_verified','confirmed':True}}}
    agent.db.commit();before=deepcopy(agent.lead.lead_profile_data)
    with patch.object(agent.db,'commit',side_effect=AssertionError('Committed')):
        result=resolve(agent.lead)
    assert result['current']['bedrooms']['status']=='unknown' and result['current']['financing']['status']=='confirmed'
    assert agent.lead.lead_profile_data==before


def test_correction_supersedes_meta_and_retains_evidence_history_without_model_value(agent):
    agent.lead.meta_form_data={'budget':'200000 USD'};agent.db.commit()
    row=pref(agent,'budget','Actually, my budget is 300000 USD')
    value=resolve(agent.lead)
    item=value['current']['budget']
    assert item['value']==row.content and item['status']=='declared' and item['source_ref']['message_id']==row.id
    assert item['captured_at'] and item['supersedes']
    assert any(old['value']=='200000 USD' for old in value['history'])
    agent.lead.meta_form_data={'budget':'100000 USD'};agent.db.commit()
    assert resolve(agent.lead)['current']['budget']['value']==row.content
    assert 'UNTRUSTED' not in json.dumps(value)


def test_meta_changes_remain_visible_when_only_another_field_was_captured(agent):
    agent.lead.meta_form_data={'budget':'200000 USD'};agent.db.commit()
    pref(agent,'bedrooms','I want two bedrooms')
    agent.lead.meta_form_data={'budget':'300000 USD'};agent.db.commit()
    assert resolve(agent.lead)['current']['budget']['value']=='300000 USD'


def test_refusal_and_negative_preference_are_preserved_and_not_reasked(agent):
    pref(agent,'budget','I prefer not to say')
    pref(agent,'financing',"I do not want financing")
    result=resolve(agent.lead)
    assert result['current']['budget']['status']=='declined'
    assert result['current']['financing']['polarity']=='negative'
    assert qualification(agent.lead,{'qualification_rules':'budget financing'})[0]==[]


def test_currency_alone_does_not_establish_a_budget(agent):
    agent.lead.meta_form_data={'budget':{'currency':'USD'}}
    assert qualification(agent.lead,{'qualification_rules':'budget'})[0]==['budget']


def test_conflicting_forms_are_unknown_instead_of_silent_choice(agent):
    agent.lead.meta_form_data={'budget':'200000 USD','field_data':[{'name':'budget','values':['300000 USD']}]}
    result=resolve(agent.lead)
    assert not known(result,'budget') and result['conflicts'][0]['field']=='budget'


def test_quoted_and_third_party_facts_are_not_customer_preferences(agent):
    pref(agent,'budget','My friend has a budget of 500000 USD')
    assert not known(resolve(agent.lead),'budget')


def test_foreign_message_cannot_update_profile(agent):
    other=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other',phone='+12025550198')
    agent.db.add(other);agent.db.commit()
    row=inbound(agent,'My budget is 400000 USD')
    row.metadata_json={'lead_id':other.id};agent.db.commit()
    with pytest.raises(Exception):capture(agent.db,agent.scope,understanding(row.content),row.id)
    assert not known(resolve(agent.lead),'budget')


def test_meta_budget_reaches_real_interpreter_and_next_question_is_not_budget(agent):
    agent.lead.meta_form_data={'budget':'250000 USD','access_token':'SECRET_NOT_FOR_MODEL'}
    agent.project.profile.profile_data={'qualification_rules':'budget, financing'}
    agent.project.profile.field_states={'qualification_rules':{'status':'confirmed','applicable':True}}
    agent.db.commit()
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    request=json.loads(agent.infer.call_args.args[1][1]['content'])
    assert request['turn_context']['lead_profile']['current']['budget']['value']=='250000 USD'
    assert 'SECRET_NOT_FOR_MODEL' not in json.dumps(request)
    assert run.output_snapshot['metadata']['qualification_offer']['field']=='financing'
    assert 'What budget range' not in agent.reply()


@pytest.mark.parametrize('status,category',[(MeetingStatus.CONFIRMED,'active'),(MeetingStatus.CANCELLED,'cancelled'),(MeetingStatus.COMPLETED,'past')])
def test_typed_appointment_reads_preserve_status_and_missing_association(agent,status,category):
    row=meeting(agent,status=status)
    result=AppointmentReadTool(agent.db,agent.scope).execute({'category':category},now=NOW)
    assert result['count']==1 and result['appointments'][0]['id']==row.id
    assert result['appointments'][0]['property_association']=='unknown_legacy'
    assert result['appointments'][0]['property_type_name'] is None and result['external_actions']==0


def test_past_visit_is_not_reported_active_and_cancelled_never_active(agent):
    meeting(agent,starts=NOW-timedelta(days=1))
    meeting(agent,status=MeetingStatus.CANCELLED)
    tool=AppointmentReadTool(agent.db,agent.scope)
    assert tool.execute(now=NOW)['count']==0
    assert tool.execute({'category':'past'},now=NOW)['count']==1


def test_appointment_query_is_scoped_to_exact_lead_and_company_not_contact(agent):
    own=meeting(agent)
    other=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other lead',phone=agent.lead.phone)
    company=Company(name='Other Company');agent.db.add_all([other,company]);agent.db.flush()
    foreign=Project(company_id=company.id,name='Foreign');agent.db.add(foreign);agent.db.commit()
    meeting(agent,lead=other)
    meeting(agent,project=foreign)  # Corrupt cross-tenant relationship must not leak.
    rows=AppointmentReadTool(agent.db,agent.scope).execute({'category':'all'},now=NOW)
    assert [r['id'] for r in rows['appointments']]==[own.id]


def test_same_lead_original_project_visit_survives_current_project_interest(agent):
    old=Project(company_id=agent.company.id,name='Original property',timezone='America/New_York');agent.db.add(old);agent.db.commit()
    booked=meeting(agent,project=old)
    newer=product(agent,'New interest')
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=newer.id
    save(agent.db,agent.scope,event_key='choose-new-interest',expected_revision=revision,state=state);agent.db.commit()
    row=inbound(agent,'Tell me about this property')
    context=build(agent.db,agent.scope,inbound_message_id=row.id,now=NOW)
    assert context['current_interest']['property_type_id']==newer.id
    assert context['appointments']['active']['appointments'][0]['project_id']==old.id
    assert booked.project_id==old.id and booked.visit_property_type_id is None


def test_booking_references_snapshot_approved_type_without_touching_other_booking(agent):
    first=product(agent,'Studio');second=product(agent,'Loft')
    row=meeting(agent,product_id=first.id)
    old=deepcopy(row.visit_context)
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=second.id
    save(agent.db,agent.scope,event_key='pivot-interest',expected_revision=revision,state=state);agent.db.commit()
    assert row.visit_property_type_id==first.id and row.visit_context==old
    assert row.visit_context['property_type_name']=='Studio'


def test_foreign_and_unapproved_booking_reference_rejected(agent):
    row=meeting(agent)
    pending=ProjectPropertyType(project=agent.project,name='Unapproved',review_status='pending');agent.db.add(pending);agent.db.commit()
    with pytest.raises(PermissionError):bind_visit(agent.db,row,company_id=agent.company.id,property_type_id=pending.id)
    with pytest.raises(PermissionError):bind_visit(agent.db,row,company_id=str(uuid.uuid4()))


def test_booking_timezone_and_address_are_not_replaced_by_current_project_data(agent):
    agent.project.timezone='America/Los_Angeles';agent.db.commit()
    row=meeting(agent,product_id=product(agent).id)
    agent.project.timezone='UTC';agent.project.address='Different address';agent.db.commit()
    result=AppointmentReadTool(agent.db,agent.scope).execute(now=NOW)['appointments'][0]
    assert result['timezone']=='America/Los_Angeles' and result['timezone_source']=='booking_snapshot'
    assert result['address']=='100 Main Street' and result['starts_at_local'].endswith('-08:00')


@pytest.mark.parametrize('category',['active','past','cancelled','all'])
def test_real_inbound_appointment_questions_are_reads_without_availability_calls(agent,category):
    # A future date relative to actual coordinator time.
    meeting(agent,starts=datetime.now(timezone.utc)+timedelta(days=3))
    text='When is my appointment?'
    u=understanding(text,'appointment').model_copy(update={'appointment_query':category})
    with patch('app.modules.sales_agent.live_service._availability_reply',side_effect=AssertionError('Read attempted scheduling')):
        _,run=agent.turn(text,u)
    assert run.status=='completed' and not run.output_snapshot['proposed_actions'],run.output_snapshot
    assert run.output_snapshot['metadata']['appointment_query']['category']==category
    assert agent.db.query(Meeting).count()==1 and not agent.conversation.is_paused


def test_no_appointment_returns_explicit_empty_without_inventing_details(agent):
    text='When is my appointment?'
    u=understanding(text,'appointment').model_copy(update={'appointment_query':'active'})
    _,run=agent.turn(text,u)
    assert 'You have no active appointments.' in agent.reply()
    assert not run.output_snapshot['metadata']['appointment_query']['appointments']
    assert not agent.db.query(Meeting).count()


def test_context_history_is_bounded_and_does_not_include_future_or_other_lead_messages(agent):
    for i in range(25):inbound(agent,'I need property information '+str(i)+' '+('x'*2000))
    current=inbound(agent,'Give me details')
    future=outbound(agent.db,agent.conversation,'FUTURE_SENTINEL',seconds=10)
    other=outbound(agent.db,agent.conversation,'FOREIGN_SENTINEL',{'lead_id':'another-lead'},seconds=-1)
    context=build(agent.db,agent.scope,inbound_message_id=current.id,now=NOW)
    assert len(context['history'])<=20 and sum(len(r['content']) for r in context['history'])<=12000
    assert 'SENTINEL' not in json.dumps(context['history'])
    assert context['history_coverage']['older_messages_omitted']


def test_structured_memory_bounded_idempotent_and_keeps_preferences_and_restrictions():
    state=DialogueState()
    for i in range(15):remember(state,message_id=str(i),at=NOW,understanding=understanding('Give me information','catalog'),answered_topics=['catalog'])
    remember(state,message_id='14',at=NOW,understanding=understanding('Give me information','catalog'),answered_topics=['catalog'])
    assert len(state.memory.recent_turns)==8 and state.memory.as_of_message_id=='14'
    assert [r['message_id'] for r in state.memory.recent_turns]==[str(i) for i in range(7,15)]
    assert state.memory.answered_topics==['catalog']


def test_successful_turn_persists_memory_and_language_hold_does_not_change_it(agent):
    agent.turn('Give me information',understanding('Give me information','catalog'))
    state=load(agent.db,agent.scope)[1]
    assert state.memory.as_of_message_id and state.memory.recent_turns
    agent.turn('Dame información',understanding('Dame información','catalog'))
    assert load(agent.db,agent.scope)[1]==state


def test_proposal_persists_without_mutating_booking_and_expires_without_authority(agent):
    row=meeting(agent);original=booking_digest(row)
    item=proposal(row)
    revision,state=propose(agent.db,agent.scope,expected_revision=0,event_key='proposal-1',proposal=item,now=NOW);agent.db.commit()
    assert booking_digest(row)==original and row.status==MeetingStatus.CONFIRMED
    context=proposal_context(agent.db,agent.scope,state,now=NOW+timedelta(minutes=21))
    assert context[0]['status']=='expired' and not context[0]['authorizes_change']
    assert context[0]['availability']=='not_checked'


def test_changed_booking_invalidates_proposal_without_freeing_original_slot(agent):
    row=meeting(agent)
    _,state=propose(agent.db,agent.scope,expected_revision=0,event_key='proposal-1',proposal=proposal(row),now=NOW)
    agent.db.commit();row.meeting_time+=timedelta(hours=1);agent.db.commit()
    assert proposal_context(agent.db,agent.scope,state,now=NOW)[0]['status']=='stale'
    assert row.status==MeetingStatus.CONFIRMED


@pytest.mark.parametrize('minutes',[-1,31])
def test_invalid_proposal_expiry_rejected(agent,minutes):
    row=meeting(agent);item=proposal(row).model_copy(update={'expires_at':NOW+timedelta(minutes=minutes)})
    with pytest.raises(ValueError):propose(agent.db,agent.scope,expected_revision=0,event_key='bad',proposal=item,now=NOW)


def test_foreign_meeting_proposal_rejected(agent):
    other=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other',phone='+12025550197');agent.db.add(other);agent.db.commit()
    row=meeting(agent,lead=other)
    with pytest.raises(PermissionError):propose(agent.db,agent.scope,expected_revision=0,event_key='bad',proposal=proposal(row),now=NOW)


def test_historical_dialogue_loads_with_empty_memory_and_proposals():
    old={'version':'sales-dialogue/1.0','selected_property_type_id':None,'tasks':[],'constraints':[],'offers':[],'preferences':[],'last_understanding':None}
    state=DialogueState.model_validate(old)
    assert state.selected_unit_id is None and not state.memory.recent_turns and not state.change_proposals


def test_visit_migration_preserves_historical_rows_and_roundtrips():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_visit_context.py'
    spec=importlib.util.spec_from_file_location('visit_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        for table in ('project_property_types','project_units'):conn.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36), lead_id VARCHAR(36), visit_address TEXT)'))
        conn.execute(text("INSERT INTO meetings VALUES ('historical','project','lead','Original address')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            row=conn.execute(text('SELECT * FROM meetings')).mappings().one()
            assert row['visit_address']=='Original address' and row['visit_property_type_id'] is None and row['visit_unit_id'] is None and row['visit_context'] is None
            module.downgrade()
            assert conn.execute(text('SELECT visit_address FROM meetings')).scalar()=='Original address'
            assert len(inspect(conn).get_columns('meetings'))==4
            module.upgrade()
    engine.dispose()


@pytest.mark.parametrize('answer',['No',False])
def test_negative_meta_financing_is_explicit_not_unknown(agent,answer):
    agent.lead.meta_form_data={'financing':answer}
    item=resolve(agent.lead)['current']['financing']
    assert item['status']=='declared' and item['polarity']=='negative'


def test_proposal_retry_is_idempotent_and_conflicting_reuse_rejected(agent):
    row=meeting(agent);item=proposal(row)
    first=propose(agent.db,agent.scope,expected_revision=0,event_key='same-event',proposal=item,now=NOW)
    agent.db.commit()
    again=propose(agent.db,agent.scope,expected_revision=0,event_key='same-event',proposal=item,now=NOW+timedelta(minutes=25))
    assert first==again and len(again[1].change_proposals)==1
    with pytest.raises(DialogueConflict):propose(agent.db,agent.scope,expected_revision=0,event_key='same-event',proposal=item.model_copy(update={'starts_at':NOW+timedelta(days=4)}),now=NOW)


def test_real_property_inquiry_pivots_interest_but_not_booked_visit(agent):
    first=product(agent,'Studio');second=product(agent,'Loft')
    row=meeting(agent,starts=datetime.now(timezone.utc)+timedelta(days=3),product_id=first.id)
    before=booking_digest(row)
    text='Tell me about Loft'
    _,run=agent.turn(text,understanding(text,'property_details',references=[dict(kind='property',expression='Loft',evidence='Loft')]))
    assert run.status=='completed' and load(agent.db,agent.scope)[1].selected_property_type_id==second.id
    assert booking_digest(row)==before and row.visit_property_type_id==first.id
    payload=json.loads(agent.infer.call_args.args[1][1]['content'])
    assert payload['turn_context']['appointments']['active']['appointments'][0]['property_type_id']==first.id


def test_actual_booking_binds_original_offer_not_later_interest(agent):
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    a=product(agent,'Studio');b=product(agent,'Loft')
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=a.id
    save(agent.db,agent.scope,event_key='initial-interest',expected_revision=revision,state=state)
    sales=User(company_id=agent.company.id,email='sales@example.invalid',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True,first_name='Test',last_name='Specialist')
    agent.db.add(sales);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=agent.project.id,user_id=sales.id,responsibility='sales',sales_enabled=True,accepts_appointments=True,is_active=True,accepts_new_leads=True))
    starts=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    agent.db.add(SalesAvailabilityBlock(user_id=sales.id,starts_at=starts,ends_at=starts+timedelta(hours=2),timezone='UTC'));agent.db.commit()
    agent.turn('I want to arrange a visit',understanding('I want to arrange a visit','appointment'))
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=b.id
    save(agent.db,agent.scope,event_key='later-interest',expected_revision=revision,state=state);agent.db.commit()
    text='3:00 PM'
    _,run=agent.turn(text,understanding(text,'appointment',references=[dict(kind='appointment',expression=text,evidence=text)]))
    booked=agent.db.query(Meeting).one()
    assert booked.visit_property_type_id==a.id and booked.visit_context['property_type_name']=='Studio',run.output_snapshot
    assert booked.visit_address=='100 Main St' and booked.meeting_time==starts


@pytest.mark.parametrize('index',range(6))
@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_real_catalog_with_synthetic_meta_budget_in_context(index,channel,monkeypatch):
    from sales_ai_support.sandbox import Sandbox,InboundHarness,load_catalog
    catalog=load_catalog();sandbox=Sandbox(catalog)
    try:
        project_id=catalog['projects'][index]['project']['id']
        h=InboundHarness(sandbox,project_id,channel,monkeypatch,understanding('Give me information','catalog'))
        monkeypatch.setattr(settings,'SALES_NEXT_FLOW_ENABLED',True)
        monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS',project_id)
        h.lead.meta_form_data={'budget':'SYNTHETIC 250000 USD','form_id':'SYNTHETIC-FORM'};h.db.commit()
        _,run=h.turn('Give me information')
        assert run.status=='completed' and not h.conversation.is_paused,run.output_snapshot
        request=json.loads(h.model.requests[0]['args'][1][1]['content'])
        assert request['turn_context']['lead_profile']['current']['budget']['value']=='SYNTHETIC 250000 USD'
        assert request['turn_context']['appointments']['active']['appointments']==[]
        assert not h.db.query(Meeting).count() and not h.calendar.calls
    finally:sandbox.close()


def test_profile_context_truncates_view_without_losing_full_evidence(agent):
    from app.modules.sales_agent.lead_profile import for_context
    long='My budget is '+('1'*1000)+' USD'
    pref(agent,'budget',long)
    full=resolve(agent.lead);view=for_context(full)
    assert full['current']['budget']['value']==long
    assert view['current']['budget']['context_truncated'] and len(view['current']['budget']['value'])==600


def test_revoked_proposal_target_does_not_block_other_conversation_state(agent):
    row=meeting(agent);target=product(agent)
    item=proposal(row,target_property_type_id=target.id)
    revision,state=propose(agent.db,agent.scope,expected_revision=0,event_key='proposal-1',proposal=item,now=NOW)
    agent.db.commit();target.review_status='pending';agent.db.commit()
    assert proposal_context(agent.db,agent.scope,state,now=NOW)[0]['status']=='revoked_or_unavailable'
    save(agent.db,agent.scope,event_key='continue-dialogue',expected_revision=revision,state=state)
    agent.db.commit()
    assert row.status==MeetingStatus.CONFIRMED


def test_valid_explicit_unit_reference_and_mismatch_validation(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    unit=ProjectUnit(project=agent.project,unit_code='A-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow())
    agent.db.add(unit);agent.db.commit()
    row=meeting(agent)
    bind_visit(agent.db,row,company_id=agent.company.id,property_type_id=a.id,unit_id=unit.id)
    assert row.visit_unit_id==unit.id and row.visit_context['unit_code']=='A-101'
    with pytest.raises(PermissionError):bind_visit(agent.db,row,company_id=agent.company.id,property_type_id=b.id,unit_id=unit.id)


def test_unknown_meeting_id_never_returns_another_appointment(agent):
    meeting(agent)
    assert not AppointmentReadTool(agent.db,agent.scope).execute({'meeting_id':str(uuid.uuid4())},now=NOW)['appointments']


def test_turn_trace_identifies_context_version_and_digest(agent):
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    assert run.output_snapshot['metadata']['turn_context_version']=='sales-turn-context/1.0'
    assert len(run.output_snapshot['metadata']['turn_context_sha256'])==64


def test_sqlite_migration_keeps_child_attachments_with_foreign_keys_enabled():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_visit_context.py'
    spec=importlib.util.spec_from_file_location('visit_migration_fk',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('PRAGMA foreign_keys=ON'))
        for table in ('project_property_types','project_units'):conn.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE attachments (id VARCHAR(36) PRIMARY KEY, meeting_id VARCHAR(36) REFERENCES meetings(id) ON DELETE CASCADE)'))
        conn.execute(text("INSERT INTO meetings VALUES ('m')"));conn.execute(text("INSERT INTO attachments VALUES ('a','m')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            assert conn.execute(text('SELECT count(*) FROM attachments')).scalar()==1
            module.downgrade()
            assert conn.execute(text('SELECT count(*) FROM attachments')).scalar()==1
            module.upgrade()
        assert conn.execute(text('PRAGMA foreign_key_check')).all()==[]
    engine.dispose()


def test_identity_uses_stored_first_name_without_exposing_phone_or_inference(agent):
    row=inbound(agent,'Give me information')
    context=build(agent.db,agent.scope,inbound_message_id=row.id,now=NOW)
    assert context['lead_identity']=={'first_name':'Example','source':'lead_record'}
    assert agent.lead.phone not in json.dumps(context)


def test_failed_dispatch_does_not_claim_answered_memory_and_retry_records_once(agent):
    agent.send.side_effect=RuntimeError('OFFLINE provider failure')
    with pytest.raises(RuntimeError):agent.turn('Give me information',understanding('Give me information','catalog'))
    assert not load(agent.db,agent.scope)[1].memory.recent_turns
    row=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    agent.send.side_effect=None;agent.retry(row);agent.retry(row)
    memory=load(agent.db,agent.scope)[1].memory
    assert memory.as_of_message_id==row.id and len(memory.recent_turns)==1
