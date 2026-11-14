"""E: real coordinator/store/dispatch with closed composer and mocked network only."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse
import pytest
from fastapi import HTTPException
from test_sales_turn_1720 import case, approved_asset, outbound
from test_sales_ai_group_b import agent, publish, review
from test_sales_ai_group_c import product, meeting
from test_sales_ai_group_d import typed, req, ref
from test_sales_active_integration import understanding
from app.modules.sales_agent import commercial_composer as composer
from app.modules.sales_agent import active_service as active
from app.modules.sales_agent.dialogue_store import load, save
from app.modules.sales_agent.models import SalesMessage, AgentRun
from app.modules.projects.models import SalesAssetShare, ProjectPropertyType, ProjectSalesAsset
from app.modules.projects import storage_service, asset_share_service
from app.modules.sales_crm.models import Meeting
from app.core.config import settings


def material(agent, tags, **kw):
    return approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),tags,**kw)


def latest(agent):
    return agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()


def context(call):
    return json.loads(call.args[2][1]['content'])


def response(payload, *, closing=None, wording='conversational'):
    return json.dumps({'version':composer.VERSION,'opening':'direct',
        'blocks':[{'evidence_id':b['id'],'wording':wording} for b in payload['evidence_blocks']],
        'continuation_id':closing or payload['continuations'][0]['id']})


@pytest.fixture
def model(agent):
    agent.config.openrouter_api_key='synthetic-never-network'
    agent.db.commit()
    async def generate(*args,**kwargs):
        assert kwargs['response_format']['json_schema']['name']=='sales_commercial_composition'
        return response(json.loads(args[2][1]['content']))
    with patch('app.integrations.openrouter_client.generate_llm_response',new=AsyncMock(side_effect=generate)) as fake:
        yield fake


def test_t01_catalog_one_close_not_catalog_plus_budget(agent,model):
    product(agent,'Studio');product(agent,'Loft')
    agent.project.profile.profile_data={'qualification_rules':'budget and timeline'}
    agent.project.profile.field_states={'qualification_rules':{'status':'confirmed','applicable':True}};agent.db.commit()
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    assert run.status=='completed' and run.output_snapshot['metadata']['composition']['status']=='accepted'
    assert latest(agent).content.count('?')==1 and 'budget range' not in latest(agent).content
    assert '1. Studio' in agent.reply() and '2. Loft' in agent.reply()
    assert latest(agent).metadata_json['property_catalog_offer']['property_type_ids']


def test_t02_single_option_has_details_and_no_redundant_type_question(agent,model):
    p=product(agent,'Only home');p.description='A private terrace.';p.features=['Separate kitchen']
    agent.project.profile.profile_data={'qualification_rules':'property type'}
    agent.project.profile.field_states={'qualification_rules':{'status':'confirmed','applicable':True}};agent.db.commit()
    agent.turn('Give me information',understanding('Give me information','catalog'))
    text=latest(agent).content
    assert 'private terrace' in text and 'Separate kitchen' in text
    assert 'Which property option' not in text and 'bedroom count would you prefer' not in text
    assert text.count('?')==1


def test_single_property_direct_details_and_material_need_no_selection_gate(agent,model):
    p=product(agent,'Only home');asset=material(agent,['floor_plan']);asset.property_type_id=p.id;agent.db.commit()
    agent.turn('Send plans and details',understanding('Send plans and details','materials','property_details',subjects={0:'floor_plan'}))
    assert agent.db.query(SalesAssetShare).one().sales_asset_id==asset.id
    assert 'Only home' in agent.reply() and 'Which property' not in latest(agent).content
    assert not load(agent.db,agent.scope)[1].selected_property_type_id  # Query targeting isn't declared interest.


def test_t09_known_meta_fields_not_reasked_and_context_reaches_composer(agent,model):
    product(agent)
    agent.lead.meta_form_data={'budget':'100000 USD','purchase_timeline':'Next month'}
    agent.project.profile.profile_data={'qualification_rules':'budget and purchase timing'}
    agent.project.profile.field_states={'qualification_rules':{'status':'confirmed','applicable':True}};agent.db.commit()
    agent.turn('Give me information',understanding('Give me information','catalog'))
    payload=context(model.call_args)
    profile=payload['turn_context']['lead_profile']['current']
    assert profile['budget']['status']=='declared' and profile['purchase_timeline']['status']=='declared'
    assert 'budget range' not in agent.reply() and 'planning to buy' not in agent.reply()


def test_published_stage_segment_objection_and_original_model_reach_composer(agent,model):
    from app.modules.sales_crm.models import LeadObjection
    product(agent)
    agent.lead.pipeline_stage='S04';agent.lead.assigned_segment='stale-inferred-segment'
    agent.lead.meta_form_data={'buyer_type':'rental_yield_investor'}
    agent.db.add(LeadObjection(lead_id=agent.lead.id,objection_type='price',evidence='too expensive'))
    publish(agent,{**agent.config.agent_ventas,'model':'test/offline','stage_prompts':{'S04':'Explain value first'},
        'segment_prompts':{'rental_yield_investor':'Do not promise returns'},'objection_prompts':{'price':'Explain approved payment options'}})
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    data=context(model.call_args)['published_guidance']
    assert data['guidance']['stage']=='Explain value first' and data['guidance']['segment']=='Do not promise returns'
    assert data['guidance']['objections']==['Explain approved payment options']
    assert model.call_args.args[1]=='test/offline' and run.output_snapshot['metadata']['composition']['playbook_selection']==data['selection']


@pytest.mark.parametrize('bad',[
    {'text':'Guaranteed 20% returns and your visit is booked.'},
    {'url':'https://unapproved.invalid/file.pdf'},
    {'opening':'Hola'},
    {'blocks':[{'evidence_id':'foreign-secret','wording':'direct'}]},
    {'blocks':[]},
    {'continuation_id':'book_now'},
    {'blocks':[{'evidence_id':'e0','wording':'invented'}]},
])
def test_hallucinated_facts_actions_links_language_or_missing_evidence_repaired(agent,model,bad):
    product(agent)
    calls=[]
    async def generate(*args,**kwargs):
        payload=json.loads(args[2][1]['content']);value=json.loads(response(payload));calls.append(payload)
        if len(calls)==1:value.update(bad)
        return json.dumps(value)
    model.side_effect=generate
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    trace=run.output_snapshot['metadata']['composition']
    assert [a['status'] for a in trace['attempts']]==['invalid_contract','accepted']
    assert model.await_count==2 and agent.infer.await_count==1
    assert 'Guaranteed' not in agent.reply() and 'unapproved.invalid' not in agent.reply() and 'Hola' not in agent.reply()
    assert not agent.db.query(Meeting).count() and not agent.conversation.is_paused


@pytest.mark.parametrize('error',[None,asyncio.TimeoutError(),RuntimeError('provider offline')])
def test_bounded_failure_preserves_verified_answer_and_one_useful_close(agent,model,error):
    product(agent)
    if error:model.side_effect=error
    else:model.return_value='not-json';model.side_effect=None
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    assert run.output_snapshot['metadata']['composition']['status']=='safe_fallback'
    assert model.await_count==(1 if error else 2)
    assert 'Studio' in agent.reply() and latest(agent).content.count('?')==1
    assert not agent.conversation.is_paused


def test_provider_retry_reuses_composition_and_shares_without_new_inference(agent,model):
    material(agent,['brochure'])
    agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):
        agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    run=agent.db.query(AgentRun).one()
    assert model.await_count==1 and agent.db.query(SalesAssetShare).count()==1
    agent.send.side_effect=lambda *args,**kw:{'sid':'accepted-retry','status':'sent'}
    agent.retry(inbound)
    assert model.await_count==1 and agent.infer.await_count==1 and agent.db.query(SalesAssetShare).count()==1
    assert agent.db.get(AgentRun,run.id).status=='completed'


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_t06_actual_file_link_receipt_and_no_raw_token_sent_to_composer(agent,model,channel):
    agent.conversation.channel=channel;asset=material(agent,['floor_plan'])
    _,run=agent.turn('Send plans',understanding('Send plans','materials',subjects={0:'floor_plan'}))
    share=agent.db.query(SalesAssetShare).one()
    assert share.sales_asset_id==asset.id and share.channel==channel and share.outbound_message_id
    trace=run.output_snapshot['metadata']
    assert trace['material_bindings'][0]['binding']['content_sha256']
    assert '/projects/a/' in agent.reply() and '/projects/a/' not in model.call_args.args[2][1]['content']
    token=latest(agent).content.split('/projects/a/')[1].split()[0].rstrip('.,;)')
    source,resolved=asset_share_service.resolve(agent.db,token)
    assert resolved.id==share.id and storage_service.read_project_file(source.storage_path,encrypted=False).startswith(b'%PDF')


def test_t07_photo_fallback_accepts_exact_file_even_when_another_is_added(agent,model):
    chosen=material(agent,['brochure'],name='Related PDF')
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    assert not agent.db.query(SalesAssetShare).count() and 'photo coverage is not confirmed' in agent.reply()
    assert latest(agent).content.count('?')==1
    material(agent,['brochure'],name='New brochure')
    agent.turn('Yes',understanding('Yes','other'))
    assert [s.sales_asset_id for s in agent.db.query(SalesAssetShare)]==[chosen.id]
    assert 'coverage is not confirmed' in latest(agent).content and not agent.conversation.is_paused


@pytest.mark.parametrize('change',['file','version','tags','name','scope','source','archived','expired','channel'])
def test_changed_proposal_never_sends_replacement(agent,model,change):
    asset=material(agent,['brochure'],name='Original PDF')
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    if change=='file':storage_service.resolve_project_file(asset.source.storage_path).write_bytes(b'changed bytes')
    elif change=='version':asset.version+=1
    elif change=='tags':asset.content_tags=['floor_plan']
    elif change=='name':asset.display_name='Replacement'
    elif change=='scope':asset.property_type_id=product(agent,'Other home').id
    elif change=='source':asset.source.storage_path=material(agent,['brochure'],name='Other PDF').source.storage_path
    elif change=='archived':asset.approval_status='archived'
    elif change=='expired':asset.valid_until=datetime.utcnow()-timedelta(seconds=1)
    elif change=='channel':asset.allowed_channels=['whatsapp']
    agent.db.commit()
    material(agent,['brochure'],name='Unrelated replacement')
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesAssetShare).count() and not agent.conversation.is_paused
    assert 'projects/a/' not in latest(agent).content


def test_expired_offer_and_manual_interruption_cannot_authorize_materials(agent,model):
    material(agent,['brochure'])
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    msg=latest(agent);data=dict(msg.metadata_json);offer=dict(data['material_offer']);offer['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    msg.metadata_json={**data,'material_offer':offer};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesAssetShare).count()
    human=outbound(agent.db,agent.conversation,'A human message');human.role='human';agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesAssetShare).count()


def test_t08_photos_or_pdf_plus_financing_and_no_visit(agent,model):
    material(agent,['brochure'])
    agent.project.profile.profile_data={'payment_methods':['Bank financing'],'qualification_rules':'visit readiness'}
    agent.project.profile.field_states={k:{'status':'confirmed','applicable':True} for k in agent.project.profile.profile_data};agent.db.commit()
    text="Send photos or a brochure and explain financing. I don't want a visit yet."
    u=typed(text,[req('photos','materials',text,subject='photos'),req('pdf','materials',text,subject='brochure'),req('finance','financing',text)],
        alternatives=[{'id':'alt','request_ids':['photos','pdf'],'evidence':text}])
    agent.turn(text,u)
    assert agent.db.query(SalesAssetShare).count()==1 and 'Bank financing' in agent.reply()
    assert not agent.db.query(Meeting).count() and not agent.conversation.is_paused
    assert all(c['id']!='visit' and c['metadata'].get('qualification_offer',{}).get('field')!='visit_readiness' for c in context(model.call_args)['continuations'])


@pytest.mark.parametrize('bad',['missing','empty','hash','path','decrypt'])
def test_unreadable_material_never_offered_or_sent(agent,model,bad):
    asset=material(agent,['brochure'])
    path=storage_service.resolve_project_file(asset.source.storage_path)
    if bad=='missing':path.unlink()
    elif bad=='empty':path.write_bytes(b'')
    elif bad=='hash':asset.source.content_hash='0'*64
    elif bad=='path':asset.source.storage_path='../../outside.pdf'
    elif bad=='decrypt':asset.source.is_encrypted=True
    agent.db.commit()
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    assert not agent.db.query(SalesAssetShare).count() and not latest(agent).metadata_json.get('material_offer')
    assert "don't have photos" in latest(agent).content.lower() and not agent.conversation.is_paused


def test_approved_encrypted_file_decrypts_and_integrity_is_bound(agent,model):
    asset=material(agent,['brochure'])
    content=b'%PDF-1.4\nSynthetic approved bytes\n%%EOF'
    saved=storage_service.store_project_file(company_id=agent.company.id,project_id=agent.project.id,
        source_id=asset.source_id,original_filename='approved.pdf',content=content)
    asset.source.storage_path=saved.relative_path;asset.source.is_encrypted=True;asset.source.content_hash=saved.content_hash;agent.db.commit()
    agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    assert agent.db.query(SalesAssetShare).count()==1
    assert latest(agent).metadata_json['material_bindings'][0]['binding']['content_sha256']==hashlib.sha256(content).hexdigest()


def test_revocation_or_byte_change_after_issue_blocks_public_access(agent,model):
    asset=material(agent,['brochure'])
    agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    token=latest(agent).content.split('/projects/a/')[1].split()[0].rstrip('.,;)')
    storage_service.resolve_project_file(asset.source.storage_path).write_bytes(b'replaced')
    with pytest.raises(HTTPException) as error:asset_share_service.resolve(agent.db,token)
    assert error.value.status_code==404


def test_material_changed_during_composer_does_not_send_stale_link_or_lose_financing(agent,model):
    asset=material(agent,['brochure'])
    agent.project.profile.profile_data={'payment_methods':['Bank financing']}
    agent.project.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};agent.db.commit()
    async def generate(*args,**kwargs):
        storage_service.resolve_project_file(asset.source.storage_path).write_bytes(b'new bytes')
        return response(json.loads(args[2][1]['content']))
    model.side_effect=generate
    agent.turn('Send a brochure and explain financing',understanding('Send a brochure and explain financing','materials','financing',subjects={0:'brochure'}))
    assert '/projects/a/' not in agent.reply() and 'Bank financing' in agent.reply() and not agent.conversation.is_paused


def test_multipart_materials_revalidate_each_subset_not_all_shares(agent,model):
    for i in range(9):material(agent,['floor_plan'],name=f'Approved layout {i} with a much longer customer facing name for the requested floor plan and property type')
    _,run=agent.turn('Send floor plans',understanding('Send floor plans','materials',subjects={0:'floor_plan'}))
    assert agent.db.query(SalesAssetShare).count()==9 and run.status=='completed'
    assert len(run.output_snapshot['delivery_parts'])>1


def test_t10_visit_invitation_has_supported_purpose_and_no_operation(agent,model):
    p=product(agent)
    async def generate(*args,**kwargs):return response(json.loads(args[2][1]['content']),closing='visit')
    model.side_effect=generate
    text='Tell me about Studio'
    _,run=agent.turn(text,typed(text,[req('d','property_details',text,ref='p')],[ref('p','property','Studio')]))
    assert 'assess the layout in person' in latest(agent).content and latest(agent).content.count('?')==1
    assert not agent.db.query(Meeting).count() and not run.output_snapshot['proposed_actions']
    assert latest(agent).metadata_json['visit_invitation']
    model.side_effect=lambda *args,**kw:response(json.loads(args[2][1]['content']))
    agent.turn('More details about Studio',typed('More details about Studio',[req('d','property_details','More details about Studio',ref='p')],[ref('p','property','Studio')]))
    assert all(c['id']!='visit' for c in context(model.call_args)['continuations'])


def test_manual_takeover_during_composition_prevents_dispatch_and_sharing(agent,model):
    material(agent,['brochure'])
    async def generate(*args,**kwargs):
        agent.conversation.is_paused=True;agent.conversation.pause_reason='Manual pause';agent.db.commit()
        return response(json.loads(args[2][1]['content']))
    model.side_effect=generate
    agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    assert agent.send.await_count==0 and agent.conversation.is_paused


@pytest.mark.parametrize('message',['STOP','Dame información'])
def test_controls_and_english_gate_skip_composer(agent,model,message):
    agent.turn(message,understanding(message,'catalog'))
    model.assert_not_called()


def test_supported_benefits_only_from_confirmed_fields(agent,model):
    product(agent)
    agent.project.profile.profile_data={'value_proposition':'Private outdoor areas.', 'key_differentiators':['Guaranteed returns!']}
    agent.project.profile.field_states={'value_proposition':{'status':'confirmed','applicable':True},'key_differentiators':{'status':'pending','applicable':True}}
    agent.db.commit()
    agent.turn('Give me information',understanding('Give me information','catalog'))
    blocks=context(model.call_args)['evidence_blocks']
    assert any(b['source']=='confirmed_project_facts.value_proposition' for b in blocks)
    assert 'Private outdoor areas' in agent.reply() and 'Guaranteed returns' not in agent.reply()


def test_no_repeat_visit_invitation_when_a_visit_already_exists(agent,model):
    p=product(agent);meeting(agent,product_id=p.id)
    text='Tell me about Studio'
    agent.turn(text,typed(text,[req('d','property_details',text,ref='p')],[ref('p','property','Studio')]))
    assert all(c['id']!='visit' for c in context(model.call_args)['continuations'])
    assert context(model.call_args)['turn_context']['appointments']['active']['count']==1


def test_material_resource_url_is_backend_issued_exact_and_revoked_if_target_changes(agent,model):
    asset=material(agent,['virtual_tour'],links=[{'kind':'virtual_tour','url':'https://example.invalid/reviewed-tour','label':'Approved tour'}])
    asset.source.storage_path=None;agent.db.commit()
    agent.turn('Send the virtual tour',understanding('Send the virtual tour','materials',subjects={0:'virtual_tour'}))
    share=agent.db.query(SalesAssetShare).one()
    assert share.target_url=='https://example.invalid/reviewed-tour'
    token=latest(agent).content.split('/projects/a/')[1].split()[0].rstrip('.,;)')
    assert asset_share_service.resolve(agent.db,token)[1].id==share.id
    asset.source.extracted_links=[{'kind':'virtual_tour','url':'https://example.invalid/replacement'}];agent.db.commit()
    with pytest.raises(HTTPException):asset_share_service.resolve(agent.db,token)


@pytest.mark.parametrize('url',['http://127.0.0.1/private','http://localhost/private','file:///etc/passwd','https://user:password@example.invalid','http://169.254.169.254/metadata'])
def test_unapproved_or_private_resource_url_cannot_be_shared(agent,model,url):
    asset=material(agent,['virtual_tour'],links=[{'kind':'virtual_tour','url':url}]);asset.source.storage_path=None;agent.db.commit()
    agent.turn('Send the virtual tour',understanding('Send the virtual tour','materials',subjects={0:'virtual_tour'}))
    assert not agent.db.query(SalesAssetShare).count()
    assert not latest(agent).metadata_json.get('material_offer') and not agent.conversation.is_paused


def test_same_property_names_do_not_mix_materials(agent,model):
    a=product(agent,'Studio');b=product(agent,'STUDIO')
    chosen=material(agent,['floor_plan'],name='A plans');chosen.property_type_id=a.id
    other=material(agent,['floor_plan'],name='B plans');other.property_type_id=b.id
    agent.db.commit();revision,state=load(agent.db,agent.scope);state.selected_property_type_id=a.id
    save(agent.db,agent.scope,event_key='choose',expected_revision=revision,state=state);agent.db.commit()
    agent.turn('Send floor plans',understanding('Send floor plans','materials',subjects={0:'floor_plan'}))
    assert [s.sales_asset_id for s in agent.db.query(SalesAssetShare)]==[chosen.id]


def test_incomplete_multipart_proposal_is_not_accepted(agent,model):
    material(agent,['brochure'])
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    msg=latest(agent);msg.metadata_json={**msg.metadata_json,'delivery_group':{'key':'incomplete','part':1,'total':2}};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesAssetShare).count()


def test_material_alternative_does_not_stack_a_qualification_question(agent,model):
    material(agent,['brochure'])
    agent.project.profile.profile_data={'qualification_rules':'budget and timeline'}
    agent.project.profile.field_states={'qualification_rules':{'status':'confirmed','applicable':True}};agent.db.commit()
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    assert latest(agent).content.count('?')==1 and not latest(agent).metadata_json.get('qualification_offer')
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(SalesAssetShare).count()==1


def test_declining_material_alternative_never_shares_it(agent,model):
    material(agent,['brochure'])
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    agent.turn('No thanks',understanding('No thanks','other'))
    assert not agent.db.query(SalesAssetShare).count() and not agent.conversation.is_paused


@pytest.mark.parametrize('index',range(6))
@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_six_exported_projects_composition_with_real_catalog_and_mocked_model(index,channel,monkeypatch):
    from sales_ai_support.sandbox import Sandbox,InboundHarness,load_catalog
    catalog=load_catalog();sandbox=Sandbox(catalog);captured=[]
    try:
        entry=catalog['projects'][index];pid=entry['project']['id']
        text='Give me property information and financing; no visit yet'
        harness=InboundHarness(sandbox,pid,channel,monkeypatch,understanding(text,'catalog','financing'))
        monkeypatch.setattr(settings,'SALES_NEXT_FLOW_ENABLED',True);monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS',pid)
        from app.modules.ai_core.models import AIConfiguration
        config=harness.db.query(AIConfiguration).one();config.openrouter_api_key='synthetic-never-network';harness.db.commit()
        async def generate(*args,**kwargs):
            data=json.loads(args[2][1]['content']);captured.append(data);return response(data)
        with patch('app.integrations.openrouter_client.generate_llm_response',new=AsyncMock(side_effect=generate)):
            _,run=harness.turn(text)
        assert run.status=='completed' and run.output_snapshot['metadata']['composition']['status']=='accepted',run.output_snapshot
        assert len(captured)==1 and captured[0]['turn_context']['current_interest']['project_id']==pid
        assert not harness.db.query(Meeting).count() and not harness.calendar.calls
        reply='\n\n'.join(r.content for r in harness.replies())
        assert reply.count('?')<=1 and not harness.conversation.is_paused
        assert run.output_snapshot['metadata']['composition']['model']=='test/offline-scripted'
    finally:sandbox.close()


@pytest.mark.parametrize('expression',['that file','the first file','Related PDF'])
def test_contextual_material_acceptance_uses_exact_offered_snapshot(agent,model,expression):
    chosen=material(agent,['brochure'],name='Related PDF')
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    material(agent,['brochure'],name='New brochure')
    text='Please send '+expression
    u=typed(text,[req('file','materials',text,ref='f')],[ref('f','material',expression)])
    agent.turn(text,u)
    assert [s.sales_asset_id for s in agent.db.query(SalesAssetShare)]==[chosen.id]
    assert 'coverage is not confirmed' in latest(agent).content


def test_new_explicit_material_name_does_not_send_other_unrequested_assets(agent,model):
    a=material(agent,['floor_plan'],name='Studio plans');material(agent,['floor_plan'],name='Other plans')
    text='Send Studio plans'
    agent.turn(text,typed(text,[req('m','materials',text,ref='m',subject='floor_plan')],[ref('m','material','Studio plans')]))
    assert [s.sales_asset_id for s in agent.db.query(SalesAssetShare)]==[a.id]


def test_material_offer_cannot_bypass_old_property_restriction_after_interest_change(agent,model):
    from app.modules.sales_agent.understanding_contract import PropertyConstraint
    p=product(agent,'Studio');other=product(agent,'Loft')
    asset=material(agent,['brochure']);asset.property_type_id=p.id;agent.db.commit()
    text='Send Studio photos'
    agent.turn(text,typed(text,[req('m','materials',text,ref='p',subject='photos')],[ref('p','property','Studio')]))
    assert latest(agent).metadata_json.get('material_offer')
    revision,state=load(agent.db,agent.scope)
    state.selected_property_type_id=other.id
    state.property_constraints.append(PropertyConstraint(topic='materials',subject='photos',scope='until_explicit_change',
        evidence='No Studio photos',property_id=p.id,binding_status='resolved'))
    save(agent.db,agent.scope,event_key='scoped-prohibition',expected_revision=revision,state=state);agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesAssetShare).count()


def test_mixed_visit_and_photo_alternative_has_only_one_acceptance_question(agent,model):
    from test_sales_ai_group_d import availability
    availability(agent);material(agent,['brochure'])
    text='Send photos and arrange a visit'
    agent.turn(text,understanding(text,'materials','appointment',subjects={0:'photos'}))
    assert latest(agent).content.count('?')<=1
    assert latest(agent).metadata_json.get('material_offer')
    assert not latest(agent).metadata_json.get('appointment_offer') and not agent.db.query(Meeting).count()


def test_approved_fact_change_during_composition_discards_stale_fact(agent,model):
    p=product(agent)
    async def generate(*args,**kwargs):
        p.starting_price=999999;p.currency='USD';agent.db.commit()
        return response(json.loads(args[2][1]['content']))
    model.side_effect=generate
    _,run=agent.turn('Give me information',understanding('Give me information','catalog'))
    assert run.error_code and '999,999' not in agent.reply() and not agent.conversation.is_paused


def test_composer_provider_request_has_bounded_completion_tokens_and_timeout(agent,model):
    product(agent)
    agent.turn('Give me information',understanding('Give me information','catalog'))
    assert model.call_args.kwargs['max_tokens']==2048
    assert model.call_args.kwargs['timeout_seconds']==8


def test_provider_client_transmits_optional_token_bound():
    from unittest.mock import Mock
    from app.integrations.openrouter_client import generate_llm_response
    fake=Mock();fake.raise_for_status.return_value=None;fake.json.return_value={'choices':[{'message':{'content':'{}'}}]}
    with patch('app.integrations.openrouter_client.httpx.AsyncClient') as factory:
        post=AsyncMock(return_value=fake);factory.return_value.__aenter__.return_value.post=post
        assert asyncio.run(generate_llm_response('offline','test/offline',[],max_tokens=2048))=='{}'
        assert post.call_args.kwargs['json']['max_tokens']==2048


@pytest.mark.parametrize('bound',[0,4097,True,'2048'])
def test_provider_client_rejects_invalid_token_bounds_before_network(bound):
    from app.integrations.openrouter_client import generate_llm_response
    with patch('app.integrations.openrouter_client.httpx.AsyncClient') as client:
        with pytest.raises(ValueError):asyncio.run(generate_llm_response('offline','test/offline',[],max_tokens=bound))
        client.assert_not_called()


def test_accepting_related_pdf_retires_original_need_only_after_provider_receipt(agent,model):
    material(agent,['brochure'])
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    old_id=next(t.id for t in load(agent.db,agent.scope)[1].tasks if t.topic.value=='materials')
    agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):agent.turn('Yes',understanding('Yes','other'))
    assert next(t for t in load(agent.db,agent.scope)[1].tasks if t.id==old_id).status!='cancelled'
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound',content='Yes').one()
    agent.send.side_effect=lambda *a,**kw:{'sid':'accepted-alternative','status':'sent'}
    agent.retry(inbound)
    old=next(t for t in load(agent.db,agent.scope)[1].tasks if t.id==old_id)
    assert old.status=='cancelled' and old.blocked_reason=='accepted_related_alternative'


def test_acceptance_with_independent_material_request_fulfills_each_need(agent,model):
    chosen=material(agent,['brochure'],name='Related PDF')
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    plans=material(agent,['floor_plan'],name='Approved plans')
    text='Send that file and floor plans'
    agent.turn(text,typed(text,[req('accepted','materials',text,ref='f'),req('plans','materials',text,subject='floor_plan')],
        [ref('f','material','that file')]))
    assert {s.sales_asset_id for s in agent.db.query(SalesAssetShare)}=={chosen.id,plans.id}
    assert all(t.status=='completed' for t in load(agent.db,agent.scope)[1].tasks if t.source_message_id==latest(agent).metadata_json['inbound_message_id'] and t.topic.value=='materials')
