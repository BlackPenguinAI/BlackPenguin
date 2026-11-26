"""HEI-02 focused contracts; deterministic doubles, no SDK/provider/DB production calls.

The new parity code is executed unchanged. Parent business services and the
existing choice/receipt contracts are doubles; the repository's full regression
and separate pinned SDK smoke are still required before any live enablement.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import re
import sys

import pytest
from sqlalchemy import Boolean, Column, DateTime, JSON, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'modules' / 'hermes_sales_core'


@pytest.fixture
def parity(monkeypatch):
    pkg = ModuleType('_hei02_test')
    pkg.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, pkg.__name__, pkg)

    def install(name, **attrs):
        mod = ModuleType(pkg.__name__ + '.' + name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        setattr(pkg, name, mod)
        return mod

    def choice(state, message):
        menu = state.get('last_presented_choice_set')
        if not menu:
            return None
        terms = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
        match = re.search(r'\b(first|second|third|fourth)\b', message, re.I)
        n = terms[match[1].lower()] if match else (int(message.strip()) if message.strip().isdigit() else None)
        if n is None:
            return None
        options = menu['options']
        return {'type': menu['type'], 'unit_id':menu.get('unit_id'),
                'status': 'resolved' if 1 <= n <= len(options) else 'ambiguous',
                'choice':options[n-1] if 1 <= n <= len(options) else {}}

    def record(state, *, menu, outbound_message_id):
        state['last_presented_choice_set'] = {**deepcopy(menu), 'source_reply_message_id':outbound_message_id}
        return state['last_presented_choice_set']

    def visible(reply, menu):
        lines = {int(m[1]): m[2].casefold() for line in reply.splitlines()
                 if (m := re.fullmatch(r'\s*([1-9])[.)]\s+(.+?)\s*', line))}
        return all(o['index'] in lines and o['label'].casefold() in lines[o['index']] for o in menu['options'])

    class Parent:
        def __init__(self, db, snapshot, *, state, buyer_message, inbound_message_id, now=None,
                     material_reader=None, **kwargs):
            self.db, self.snapshot, self.state, self.message = db, snapshot, state, buyer_message
            self.inbound_id = inbound_message_id
            self.now = now or datetime.now(timezone.utc)
            self._material_reader = material_reader
            self.menus = []
        def _rows(self):
            return deepcopy(self.snapshot.rows)
        def _details(self, args):
            f = self.state.get('conversation_focus') or {}
            ref = args.get('unit_id') or f.get('unit_id') or f.get('property_type_id')
            r = self._resolve(ref)
            return {'ok':True, 'property':deepcopy(r)} if r else {'error_code':'PROPERTY_NOT_FOUND_OR_AMBIGUOUS'}
        def _search(self, args):
            criteria = args.get('criteria') or {}
            max_price = criteria.get('max_price_usd', 9999999)
            rows = [r for r in self._rows() if r['price'] <= max_price]
            return {'ok':True,'matching_properties':rows,'criteria':criteria,
                    'search_scope':args.get('scope','temporary'),'match_count':len(rows)}
        def _slots(self, args):
            f = self.state.get('conversation_focus') or {}
            ref = f.get('unit_id') or f.get('property_type_id')
            self.state['visit_draft'] = {'unit_id':ref,'status':'hour_needed'}
            return {'ok':True,'unit_id':ref,'date':args.get('date_str')}
        def _verified_material(self, asset_id, row, tag):
            return False

    install('bp_operational_port', BPOperationalDraftPort=Parent, CONFIRM_EXPIRY_MINUTES=30, P04_TOOL_NAMES=frozenset())
    install('choice_state', resolve_visible_choice=choice, record_delivered_menu=record)
    install('bp_operation_receipts', visible_menu=visible, recap_visible=lambda *_: False)
    install('commercial_turn', search_request=lambda s: 'search' in s.lower(),
            extracted_criteria=lambda s: {'max_price_usd':400000} if '$400k' in s else {})
    install('sales_preferences', parse_declarations=lambda s: {})
    spec = importlib.util.spec_from_file_location(pkg.__name__+'.conversation_parity', ROOT/'conversation_parity.py')
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    setattr(pkg, 'conversation_parity', mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def catalog():
    return [dict(id='type-vb',reference='type-vb',kind='property_type',property_type='Van Buren',price=295000),
            dict(id='type-m',reference='type-m',kind='property_type',property_type='Monroe',price=350000),
            dict(id='type-l',reference='type-l',kind='property_type',property_type='Lincoln',price=400000)]


def state():
    return {'conversation_focus':{'project_id':'project-a','unit_id':None,'property_type_id':None,'ambiguous':False},
            'visit_draft':{'unit_id':None,'status':'idle'}, 'offered_assets':{},
            'last_presented_choice_set':None,'last_presented_units':[], 'search_preferences':{}}


def port(parity, catalog, message, data=None, assets=(), allowed=None):
    snap = SimpleNamespace(scope=SimpleNamespace(project_id='project-a'),rows=catalog,
                           commercial={'available_assets':list(assets),'property_types':[]})
    p = parity.ParityOperationalPort(None,snap,state=data if data is not None else state(),
                    buyer_message=message,inbound_message_id='in-1',
                    material_reader=lambda aid,row,tag: allowed is not None and (aid,row['reference'],tag) in allowed)
    context = {}
    p.prepare_context(context)
    return p, context


def test_exact_commercial_name_sets_focus(parity,catalog):
    p,c = port(parity,catalog,'I am interested in Van Buren')
    assert c['focused_property']['reference']=='type-vb'
    assert p.state['conversation_focus']['property_type_id']=='type-vb'
    assert p._details({})['property']['display_name']=='Van Buren'


def test_implicit_details_cannot_change_selected_home(parity,catalog):
    p,_=port(parity,catalog,'Van Buren')
    nxt,c=port(parity,catalog,'How much is it?',p.state)
    assert c['focused_property']['display_name']=='Van Buren'
    assert nxt._details({'unit_id':'type-m'})['error_code']=='PROPERTY_REFERENCE_CONFLICT'
    assert nxt._details({})['property']['reference']=='type-vb'


def test_new_property_keeps_visit_draft(parity,catalog):
    p,_=port(parity,catalog,'Van Buren')
    p.state['visit_draft']={'unit_id':'type-vb','status':'day_needed'}
    nxt,c=port(parity,catalog,'Tell me about Monroe instead',p.state)
    assert c['focused_property']['reference']=='type-m'
    assert nxt.state['visit_draft']['unit_id']=='type-vb'
    assert nxt._details({})['property']['reference']=='type-m'


def test_multi_name_is_not_one_focus(parity,catalog):
    p,c=port(parity,catalog,'Compare Van Buren and Monroe')
    assert c['focused_property'] is None
    assert p.state['conversation_focus']['ambiguous']
    assert p._details({})['error_code']=='PROPERTY_NOT_FOUND_OR_AMBIGUOUS'


def test_duplicate_commercial_name_is_not_invented(parity,catalog):
    duplicate={**catalog[0],'id':'other','reference':'other'}
    p,c=port(parity,catalog+[duplicate],'Van Buren')
    assert c['focused_property'] is None
    assert p._resolve('Van Buren') is None


def test_generic_category_does_not_choose_an_exact_property(parity,catalog):
    p,c=port(parity,catalog+[dict(id='apt',reference='apt',kind='property_type',property_type='Apartment',price=1)],'I want an apartment')
    assert c['focused_property'] is None


def test_menu_uses_displayed_order_and_subset(parity,catalog):
    reply='Here are two homes:\n1. Lincoln - $400,000\n2. Van Buren - $295,000'
    menu=parity.delivered_property_menu(reply,catalog)
    assert [x['unit_id'] for x in menu['options']]==['type-l','type-vb']
    s=state(); assert parity.commit_property_menu(s,[menu],reply,'out-1')
    p,c=port(parity,catalog,'second option',s)
    assert c['focused_property']['reference']=='type-vb'
    assert p._details({})['property']['reference']=='type-vb'


@pytest.mark.parametrize('reply',[
    '1. Van Buren\n2. Unknown house',
    '1. Van Buren\n1. Monroe',
    '1. Van Buren\n3. Monroe',
    '1. Van Buren\n2. Van Buren',
    '1. Van Buren and Monroe\n2. Lincoln',
    '1. Has three bedrooms\n2. Has two bathrooms',
])
def test_no_unproven_property_menu(parity,catalog,reply):
    assert parity.delivered_property_menu(reply,catalog) is None


def test_inline_verified_list_normalized(parity,catalog):
    reply,menu=parity.normalize_property_list('Options: 1. Van Buren 2. Monroe',catalog)
    assert reply=='Options:\n1. Van Buren\n2. Monroe'
    assert [o['unit_id'] for o in menu['options']]==['type-vb','type-m']


def test_unverified_inline_prose_preserved(parity,catalog):
    text='1. Van Buren 2. Unverified'
    assert parity.normalize_property_list(text,catalog)==(text,None)


def test_no_hidden_results_after_search(parity,catalog):
    p,_=port(parity,catalog,'search options')
    p._search({'criteria':{}})
    assert p.finalize_reply('We have several homes.')=='We have several homes.'
    assert p.menus==[] and p.state['last_presented_units']==[]


def test_stale_menu_from_previous_engine_is_cleared(parity,catalog):
    s=state(); reply='1. Van Buren\n2. Monroe'
    parity.commit_property_menu(s,[parity.delivered_property_menu(reply,catalog)],reply,'out-1')
    parity.invalidate_stale_choice(s,SimpleNamespace(id='new-legacy-out',content='A new response'))
    assert s['last_presented_choice_set'] is None and s['last_presented_units']==[]


def test_budget_not_expanded_by_model_alone(parity,catalog):
    s=state();s['search_preferences']={'budget':{'maximum_usd':300000}}
    p,_=port(parity,catalog,'search again',s)
    result=p._search({'criteria':{'max_price_usd':400000},'scope':'temporary'})
    assert result['criteria']['max_price_usd']==300000
    assert result['match_count']==1
    assert s['search_preferences']['budget']['maximum_usd']==300000


def test_explicit_temporary_budget_does_not_rewrite_primary(parity,catalog):
    s=state();s['search_preferences']={'budget':{'maximum_usd':300000}}
    p,_=port(parity,catalog,'search under $400k',s)
    result=p._search({'criteria':{'max_price_usd':400000},'scope':'temporary'})
    assert result['match_count']==3
    assert s['search_preferences']['budget']['maximum_usd']==300000
    assert s['active_search']['scope']=='temporary'


def test_visit_date_menu_keeps_original_property(parity,catalog):
    s=state();parity.set_focus(s,catalog[1],'project-a')
    s['visit_draft']={'unit_id':'type-vb','status':'day_needed'}
    s['last_presented_choice_set']={'type':'visit_day','unit_id':'type-vb','options':[
        {'index':1,'date':'2026-12-01'},{'index':2,'date':'2026-12-02'}]}
    p,c=port(parity,catalog,'second option',s)
    out=p._slots({})
    assert out['unit_id']=='type-vb' and out['date']=='2026-12-02'
    assert p.state['conversation_focus']['property_type_id']=='type-m'


def test_unique_verified_pdf_is_draft_only(parity,catalog):
    assets=[dict(asset_id='pdf-1',name='VB brochure',asset_type='brochure',content_tags=['brochure'])]
    p,_=port(parity,catalog,'Van Buren send the PDF',assets=assets,allowed={('pdf-1','type-vb','brochure')})
    res=p._media_request({})
    assert res['delivery']=='pending_backend_share' and res['share_issued'] is False
    assert p.state['offered_assets']['pending_request']['asset_ids']==['pdf-1']


def test_generic_pdf_with_multiple_verified_categories_requires_choice(parity,catalog):
    assets=[dict(asset_id='pdf-1',name='VB brochure',asset_type='brochure'),dict(asset_id='pdf-2',name='VB floor plan',asset_type='floor_plan')]
    p,_=port(parity,catalog,'Van Buren send the PDF',assets=assets,allowed={('pdf-1','type-vb','brochure'),('pdf-2','type-vb','floor_plan')})
    assert p._media_request({})['error_code']=='MEDIA_TYPE_REQUIRED'
    assert not p.state['offered_assets']


def test_offer_needs_verified_asset_and_yes_uses_its_subject(parity,catalog):
    assets=[dict(asset_id='pdf-1',name='VB brochure',asset_type='brochure')]
    allowed={('pdf-1','type-vb','brochure')}
    p,_=port(parity,catalog,'Van Buren',assets=assets,allowed=allowed)
    p._assets({});p.finalize_reply('Would you like the brochure?')
    assert p.offered_media=={'unit_id':'type-vb','subject':'brochure'}
    p.state['offered_assets']['presented_offer']={**p.offered_media,'source_reply_message_id':'out-1'}
    nxt,_=port(parity,catalog,'Yes please',p.state,assets,allowed)
    assert nxt._media_request({})['share_issued'] is False


def test_foreign_asset_not_exposed_as_available(parity,catalog):
    assets=[dict(asset_id='pdf-1',name='Other project brochure',asset_type='brochure')]
    p,_=port(parity,catalog,'Van Buren send brochure',assets=assets,allowed=set())
    assert p._media_request({})['delivery']=='unavailable'
    assert p._assets({})['assets']==[]


def test_scoped_history_excludes_old_activation_foreign_and_hidden_rows(parity,monkeypatch):
    base=declarative_base()
    class C(base):
        __tablename__='c';id=Column(String,primary_key=True);conversation_id=Column(String);lead_id=Column(String)
        is_active=Column(Boolean);activated_at=Column(DateTime)
    class M(base):
        __tablename__='m';id=Column(String,primary_key=True);conversation_id=Column(String);channel=Column(String)
        direction=Column(String);role=Column(String);status=Column(String);content=Column(String)
        created_at=Column(DateTime);metadata_json=Column(JSON)
    models=ModuleType('app.modules.sales_agent.models');models.SalesConversationLeadContext=C;models.SalesMessage=M
    monkeypatch.setitem(sys.modules,models.__name__,models)
    engine=create_engine('sqlite:///:memory:');base.metadata.create_all(engine)
    session=sessionmaker(bind=engine)()
    now=datetime(2026,11,26,12)
    session.add(C(id='c',conversation_id='conv',lead_id='lead',is_active=True,activated_at=now))
    def row(i,delta,content,role='assistant',status='sent',metadata=None):
        return M(id=i,conversation_id='conv',channel='simulation',role=role,
            direction='inbound' if role=='user' else 'outbound',status=status,content=content,
            created_at=now+timedelta(seconds=delta),metadata_json=metadata or {'lead_id':'lead','project_id':'project-a'})
    current=row('cur',9,'second option','user','received')
    session.add_all([row('old',-1,'old activation'),row('foreign',1,'another lead',metadata={'lead_id':'foreign'}),
        row('draft',2,'not visible',status='pending'),row('resume',3,'internal',metadata={'resume_context':True}),
        row('visible',4,'1. Van Buren\n2. Monroe'),current]);session.commit()
    try:
        history,latest=parity.scoped_dialogue(session,SimpleNamespace(conversation_id='conv',lead_id='lead',project_id='project-a'),
            SimpleNamespace(id='conv',channel='simulation'),current)
        assert history==[{'role':'assistant','content':'1. Van Buren\n2. Monroe'}]
        assert latest.id=='visible'
    finally:
        session.close();engine.dispose()
