"""HEI-03B continuation: focalized contracts with SQLite and service doubles.

No provider calls, model calls or production database. The legacy test fixture
is intentionally isolated; this tests the explicit Hermes handoff separately.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest
from test_bp_hei03b_production_tools import prod, unit
from test_bp_hei01a_engine_selection import unit as router_unit, seed_job, set_stored


@pytest.fixture
def live(prod):
    m=prod.load('live_receipts');material=prod.load('live_materials');coord=prod.load('live_coordinator')
    return NS(p=prod,receipt=m,material=material,coord=coord)


def fixture_rows(live):
    scope=live.p.u.scope
    now=datetime(2026,11,26,12)
    pin={**scope.__dict__,'event_id':'telnyx:in-1','engine':'hermes','policy_version_id':'version-1'}
    inbound=NS(id='in-1',conversation_id=scope.conversation_id,direction='inbound',role='user',
        channel='sms',provider_message_id='provider-in',created_at=now,
        metadata_json={'lead_id':scope.lead_id,'project_id':scope.project_id,'sales_engine_pin':pin})
    run=NS(id='run-1',event_id=pin['event_id'],conversation_id=scope.conversation_id,mode='live',
        graph_version='hermes/live/1',status='running',prompt_configuration_id='version-1',
        input_snapshot={'message_id':inbound.id,'sales_engine_pin':pin,'continuity_epoch':3},output_snapshot={})
    row=NS(id='reply-1',channel='sms',created_at=now+timedelta(seconds=1),content='A verified answer.',
        metadata_json={'engine':'hermes-agent','agent_run_id':run.id,'hermes_inbound_message_id':inbound.id,
                       'delivery_group':{'key':'hermes:reply:run-1','part':1,'total':1}})
    out=NS(agent_run_id=run.id,idempotency_key='hermes:reply:run-1')
    return scope,inbound,run,pin,row,out


def test_valid_live_binding(live):
    live.receipt.validate_binding(*fixture_rows(live))


@pytest.mark.parametrize('change',['legacy','simulation','missing_epoch','foreign_inbound','wrong_event','wrong_run',
    'old_reply','multi_part','wrong_group','missing_provider','wrong_project','wrong_policy','wrong_channel'])
def test_invalid_live_binding_rejected(live,change):
    scope,inbound,run,pin,row,out=fixture_rows(live)
    if change=='legacy':run.graph_version='sales-langgraph/2.0'
    elif change=='simulation':run.mode='simulation'
    elif change=='missing_epoch':run.input_snapshot.pop('continuity_epoch')
    elif change=='foreign_inbound':inbound.metadata_json['lead_id']='other'
    elif change=='wrong_event':run.event_id='another'
    elif change=='wrong_run':out.agent_run_id='another'
    elif change=='old_reply':row.created_at=inbound.created_at-timedelta(seconds=1)
    elif change=='multi_part':row.metadata_json['delivery_group']['total']=2
    elif change=='wrong_group':out.idempotency_key='other'
    elif change=='missing_provider':inbound.provider_message_id=None
    elif change=='wrong_project':inbound.metadata_json['project_id']='other'
    elif change=='wrong_policy':run.prompt_configuration_id='different'
    elif change=='wrong_channel':row.channel='whatsapp'
    with pytest.raises(live.p.m.ProductionToolError):live.receipt.validate_binding(scope,inbound,run,pin,row,out)


@pytest.mark.parametrize('module,name,kwargs',[
    ('receipt','commit_live_receipt',{'run_id':'r','outbound_message_id':'out'}),
    ('material','issue_live_material_batch',{'inbound_message_id':'in'}),
    ('material','complete_live_material_batch',{'inbound_message_id':'in','message_ids':['out']}),
    ('coord','persist_live_draft',{'inbound_message_id':'in','run_id':'r','turn':None}),
    ('coord','reconcile_live_reply',{'inbound_message_id':'in','run_id':'r','outbound_message_id':'out'}),
    ('coord','advance_live_effects',{'inbound_message_id':'in'})])
def test_gate_before_db_access(live,module,name,kwargs):
    with pytest.raises(live.p.u.selection.EngineUnavailable):getattr(getattr(live,module),name)(None,live.p.u.scope if module!='receipt' else None,**kwargs)


def test_preparation_gate_before_database(prod):
    m=prod.load('live_preparation')
    with pytest.raises(prod.u.selection.EngineUnavailable):m.prepare_live_turn(None,prod.u.scope,inbound_message_id='in',run_id='run')
    with pytest.raises(prod.u.selection.EngineUnavailable):m.reserve_live_run(None,prod.u.scope,inbound_message_id='in')


def mock_menu_helpers(live):
    p=live.p
    def visible(reply,menu):return all(x['label'] in reply for x in menu['options'])
    def recap(reply,proposal):return all(proposal[k] in reply for k in ('unit_id','date','start_time')) and '?' in reply
    def record(state,*,menu,outbound_message_id):return {**deepcopy(menu),'source_reply_message_id':outbound_message_id}
    def commit(state,menus,reply,outbound_id):
        for menu in menus:
            if menu['type']=='property' and visible(reply,menu):
                state['last_presented_choice_set']=record(state,menu=menu,outbound_message_id=outbound_id)
                break
    p.install(p.pkg.__name__+'.bp_operation_receipts',recap_visible=recap,visible_menu=visible)
    p.install(p.pkg.__name__+'.choice_state',record_delivered_menu=record)
    p.install(p.pkg.__name__+'.conversation_parity',commit_property_menu=commit)


def turn_for(live,reply,state,menus=(),media=None):
    return NS(prepared=NS(scope=live.p.u.scope,inbound_message_id='in-1',expected_revision=0,
        result=NS(reply=reply,tool_observations=[]),proposed_state=state),proposed_menus=list(menus),presented_media_offer=media)


def test_visible_menu_only(live):
    mock_menu_helpers(live)
    menu={'type':'property','options':[{'index':1,'label':'Van Buren'},{'index':2,'label':'Monroe'}]}
    reply='1. Van Buren\n2. Monroe'
    turn=turn_for(live,reply,{},[menu])
    state=live.receipt.state_for_accepted_reply(turn,NS(id='out',content=reply))
    assert state['last_presented_choice_set']['source_reply_message_id']=='out'
    assert state['last_presented_choice_set']['options']==menu['options']
    assert turn.prepared.proposed_state=={}


def test_hidden_menu_and_stale_offer_do_not_become_selectable(live):
    mock_menu_helpers(live)
    menu={'type':'visit_time','unit_id':'type-a','proposal_id':'p','options':[{'label':'10:00'},{'label':'11:00'}]}
    state={'last_slot_search':{'source_inbound_message_id':'in-1','unit_id':'type-a','proposal_id':'p','source_reply_message_id':'old'}}
    turn=turn_for(live,'No verified times.',state,[menu])
    out=live.receipt.state_for_accepted_reply(turn,NS(id='new',content='No verified times.'))
    assert out['last_presented_choice_set'] is None and out['last_slot_search']['source_reply_message_id'] is None


def test_reply_mutation_rejected(live):
    mock_menu_helpers(live)
    with pytest.raises(live.p.m.ProductionToolError):live.receipt.state_for_accepted_reply(turn_for(live,'original',{}),NS(id='new',content='changed'))


@pytest.mark.parametrize('missing',[None,'timezone','address','time','confirmation'])
def test_booking_recap_requires_full_visible_location_and_timezone(live,missing):
    mock_menu_helpers(live)
    prop={'kind':'book','status':'recap_required','selected_inbound_message_id':'in-1','unit_id':'H-201',
          'date':'2026-11-27','start_time':'10:00','timezone':'America/Lima','visit_address':'123 Main Street'}
    reply='Confirm H-201 on 2026-11-27 at 10:00 (America/Lima), 123 Main Street?'
    replacements={'timezone':'America/Lima','address':'123 Main Street','time':'10:00','confirmation':'?'}
    if missing:reply=reply.replace(replacements[missing],'')
    state=live.receipt.state_for_accepted_reply(turn_for(live,reply,{'confirmation_request':prop}),NS(id='reply',content=reply))
    assert state['confirmation_request']['status']==('recap_required' if missing else 'awaiting_confirmation')


def test_material_message_keeps_exact_urls_and_sanitizes_title(live):
    urls=['https://example.invalid/api/v1/projects/a/token1','https://example.invalid/api/v1/projects/a/token2']
    text=live.material.material_message([{'name':'Plan\n2. injected','url':urls[0]},{'name':'https://foreign.invalid','url':urls[1]}])
    assert all(url in text for url in urls) and 'foreign.invalid' not in text
    assert text.count('\n')==4


@pytest.mark.parametrize('url',['javascript:alert(1)','https://example.invalid/download/token','https://example.invalid/projects/a/',
    'https://u:p@example.invalid/projects/a/token','https://example.invalid/projects/a/t?x=y','https://example.invalid/projects/a/t#f',
    'https://example.invalid/projects/a/token extra'])
def test_invalid_issued_url_is_rejected(live,url):
    with pytest.raises(live.p.m.ProductionToolError):live.material.material_message([{'name':'PDF','url':url}])


@pytest.mark.parametrize('kind',['none','profile','book','material','both','cancel'])
def test_effect_selection_is_inbound_scoped(live,kind):
    state={'search_preferences':{'last_source_message_id':'other'},'offered_assets':{},'confirmation_request':{}}
    if kind=='profile':state['search_preferences']['last_source_message_id']='in-1'
    if kind in {'book','both','cancel'}:state['confirmation_request']={'kind':'cancel' if kind=='cancel' else 'book','status':'execution_requested','confirmed_inbound_message_id':'in-1'}
    if kind in {'material','both'}:state['offered_assets']={'pending_request':{'source_inbound_message_id':'in-1'}}
    if kind in {'both','cancel'}:
        with pytest.raises(live.p.m.ProductionToolError):live.coord.next_native_effect(state,'in-1')
    else:assert live.coord.next_native_effect(state,'in-1')=={'kind':kind if kind in {'book','material'} else None,'preferences':kind=='profile'}


def mock_draft_classes(live):
    p=live.p
    p.install(p.pkg.__name__+'.bp_turn',PreparedHermesTurn=lambda **kw:NS(**kw))
    p.install(p.pkg.__name__+'.bp_p04_turn',P04PreparedTurn=lambda **kw:NS(**kw))
    p.install(p.pkg.__name__+'.bp_state_store',_forbidden_key=lambda value:None)


def test_durable_draft_roundtrip_and_tamper_detection(live):
    mock_draft_classes(live)
    draft=turn_for(live,'An answer.',{'conversation_focus':{'unit_id':'H-201'}})
    envelope=live.coord.draft_envelope(draft)
    restored=live.coord.restore_draft(envelope,live.p.u.scope,'in-1')
    assert restored.prepared.result.reply=='An answer.'
    assert restored.prepared.proposed_state==draft.prepared.proposed_state
    envelope['payload']['reply']='tampered'
    with pytest.raises(live.p.m.ProductionToolError):live.coord.restore_draft(envelope,live.p.u.scope,'in-1')


def test_draft_never_contains_model_generated_share(live):
    mock_draft_classes(live)
    with pytest.raises(live.p.m.ProductionToolError):live.coord.draft_envelope(turn_for(live,'https://x.invalid/projects/a/fake',{}))


def test_explicit_handler_called_once_after_pin_committed(router_unit,monkeypatch):
    u=router_unit;seed_job(u)
    with u.factory() as db:set_stored(u,db,'hermes')
    monkeypatch.setattr(u.selection,'live_hermes_ready',lambda:True)
    calls=[]
    async def legacy(_):pytest.fail('No fallback allowed')
    async def hermes(job):
        with u.factory() as db:assert db.get(u.Message,'m1').metadata_json['sales_engine_pin']['engine']=='hermes'
        calls.append(job)
    assert asyncio.run(u.router.route_live_job('j1',inbound=True,legacy_handler=legacy,hermes_handler=hermes)) is True
    assert calls==['j1']


def test_handler_does_not_enable_production_gate(router_unit):
    u=router_unit;seed_job(u)
    with u.factory() as db:set_stored(u,db,'hermes')
    async def no(_):pytest.fail('Readiness gate was bypassed')
    assert asyncio.run(u.router.route_live_job('j1',inbound=True,legacy_handler=no,hermes_handler=no)) is False


def test_followup_does_not_enter_inbound_handler(router_unit,monkeypatch):
    u=router_unit;seed_job(u,inbound=False)
    with u.factory() as db:set_stored(u,db,'hermes')
    monkeypatch.setattr(u.selection,'live_hermes_ready',lambda:True)
    async def no(_):pytest.fail('An unsupported follow-up was dispatched')
    assert asyncio.run(u.router.route_live_job('j1',inbound=False,legacy_handler=no,hermes_handler=no)) is False


@pytest.fixture
def issued_batch(live,monkeypatch):
    p=live.p;scope,inbound,run,pin,row,out=fixture_rows(live)
    monkeypatch.setattr(p.u.selection,'live_hermes_ready',lambda:True)
    conversation=NS(channel='sms')
    draft={'id':'req-1','asset_ids':['asset-1','asset-2'],'source_inbound_message_id':inbound.id,'unit_id':'type-a','subject':'brochure'}
    receipt=NS(revision=5,state_after={'offered_assets':{'pending_request':draft}})
    loaded=NS(revision=5,data=deepcopy(receipt.state_after))
    monkeypatch.setattr(p.m,'_load_live_turn',lambda *a,**k:(conversation,None,None,inbound,run,row,receipt,loaded))
    bindings=[{'asset_id':v,'source_id':'source-'+v,'name':'Document '+v,'target_url':None} for v in draft['asset_ids']]
    monkeypatch.setattr(p.m,'prepare_live_material_batch',lambda *a,**k:{'request_id':draft['id'],'bindings':bindings})
    calls=[];stored=[]
    def issue(db,**kw):
        calls.append(kw)
        token='private-token-'+kw['sales_asset_id']
        return 'https://example.invalid/api/v1/projects/a/'+token,NS(id='share-'+kw['sales_asset_id'],
            token_hash=sha256(token.encode()).hexdigest(),**{k:v for k,v in kw.items() if k in {
                'company_id','project_id','lead_id','source_id','sales_asset_id','channel','agent_run_id'}})
    p.install('app.modules.projects.asset_share_service',issue=issue)
    p.install(p.pkg.__name__+'.bp_operation_models',HermesSalesOperation=lambda **kw:NS(id='op-1',**kw))
    class Query:
        def filter_by(self,**kw):return self
        def one_or_none(self):return stored[0] if stored else None
    db=NS(query=lambda model:Query(),add=stored.append,flush=lambda:None)
    return NS(live=live,db=db,scope=scope,inbound=inbound,stored=stored,calls=calls,bindings=bindings)


def test_issue_batch_binds_native_shares_without_token_in_operation(issued_batch):
    x=issued_batch
    result=x.live.material.issue_live_material_batch(x.db,x.scope,inbound_message_id=x.inbound.id)
    assert result['delivery']=='not_sent' and len(x.calls)==2
    assert result['metadata']['sales_asset_share_ids']==['share-asset-1','share-asset-2']
    assert all(c['agent_run_id']=='run-1' and c['channel']=='sms' for c in x.calls)
    assert 'private-token-' in result['content']
    assert x.stored[0].status=='pending_delivery'
    assert 'private-token-' not in str(x.stored[0].result_json)
    assert 'http' not in str(x.stored[0].result_json)
    assert x.stored[0].result_json['group_key']==result['idempotency_key']


def test_issued_batch_cannot_be_reminted(issued_batch):
    x=issued_batch
    x.live.material.issue_live_material_batch(x.db,x.scope,inbound_message_id=x.inbound.id)
    with pytest.raises(x.live.p.m.ProductionToolError,match='already exists'):
        x.live.material.issue_live_material_batch(x.db,x.scope,inbound_message_id=x.inbound.id)
    assert len(x.calls)==2


def test_batch_binding_order_cannot_change(issued_batch):
    x=issued_batch;x.bindings.reverse()
    with pytest.raises(x.live.p.m.ProductionToolError,match='differ'):
        x.live.material.issue_live_material_batch(x.db,x.scope,inbound_message_id=x.inbound.id)
    assert not x.calls and not x.stored


def test_provisional_plan_preserves_stable_event_and_reply(live,monkeypatch):
    mock_draft_classes(live)
    monkeypatch.setattr(live.p.u.selection,'live_hermes_ready',lambda:True)
    scope,inbound,run,pin,row,out=fixture_rows(live)
    draft=turn_for(live,'A verified reply.',{})
    run.output_snapshot={'live_draft':live.coord.draft_envelope(draft)}
    first=live.coord.provisional_delivery_plan(run,scope,inbound.id)
    assert first==live.coord.provisional_delivery_plan(run,scope,inbound.id)
    assert first['idempotency_key']=='hermes:reply:run-1'
    assert first['metadata']['continuity_epoch']==3
    assert first['metadata']['engine']=='hermes-agent'
    run.input_snapshot['sales_engine_pin']={**pin,'engine':'langgraph'}
    with pytest.raises(live.p.m.ProductionToolError):live.coord.provisional_delivery_plan(run,scope,inbound.id)


def test_effect_order_profile_before_booking(live,monkeypatch):
    p=live.p;scope,inbound,run,pin,row,out=fixture_rows(live)
    monkeypatch.setattr(p.u.selection,'live_hermes_ready',lambda:True)
    receipt=NS(state_after={'search_preferences':{'last_source_message_id':inbound.id},
        'confirmation_request':{'kind':'book','status':'execution_requested','confirmed_inbound_message_id':inbound.id}})
    monkeypatch.setattr(p.m,'_load_live_turn',lambda *a,**k:(None,None,None,inbound,run,row,receipt,None))
    calls=[]
    def profile(*a,**kw):calls.append('profile');return {'status':'persisted'}
    def booking(*a,**kw):calls.append('book');return {'status':'confirmed','delivery':'not_sent'}
    monkeypatch.setattr(p.m,'persist_live_preferences',profile)
    monkeypatch.setattr(p.m,'execute_first_live_booking',booking)
    result=live.coord.advance_live_effects(None,scope,inbound_message_id=inbound.id)
    assert calls==['profile','book']
    assert result['effect']['status']=='confirmed' and result['effect']['delivery']=='not_sent'
