"""P08 hermetic simulation lane. No pinned SDK, OpenRouter or provider calls.

CI's real Hermes SDK import and OpenRouter staging journey are separate gates.
"""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from test_bp_hermes_p03_state import orm, db, SCOPE
from app.modules.hermes_sales_core.contracts import TurnResult


@pytest.fixture
def env(orm, db):
    lead = db.get(orm.Lead, SCOPE.lead_id)
    lead.is_demo = True
    lead.is_opt_out = False
    lead.consent_status = 'granted_simulation'
    lead.agent_status = 'active'
    conversation = db.get(orm.SalesConversation, SCOPE.conversation_id)
    conversation.is_paused = False
    # The shared P03 fixture contains an earlier illustrative Hermes output;
    # it is not a P08 receipt and must not be mistaken for this lane's reply.
    prior = db.get(orm.SalesMessage, 'reply-a')
    prior.metadata_json = {'lead_id': SCOPE.lead_id, 'engine': 'sales-current'}
    db.flush()  # SessionLocal(autoflush=False) must persist the fixture correction.
    inbound = db.get(orm.SalesMessage, 'inbound-a')
    inbound.content = 'What is available?'
    return SimpleNamespace(db=db, lead=lead, conversation=conversation, inbound=inbound, orm=orm)


def _fake_prepare(env, calls):
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    def prepare(db, scope, **kwargs):
        calls.append(kwargs)
        assert scope == SCOPE
        return P04PreparedTurn(
            prepared=PreparedHermesTurn(
                scope=SCOPE, inbound_message_id='inbound-a', expected_revision=0,
                result=TurnResult('1. Verified home\n2. Verified apartment', [], []),
                proposed_state=env.orm.store.blank_state(SCOPE)),
            proposed_menus=[],
        )
    return prepare


def _run(env, prepare, **overrides):
    from app.modules.hermes_sales_core.p08_simulation import execute_staged_simulation
    return execute_staged_simulation(
        env.db, SCOPE, inbound_message_id='inbound-a', settings=object(),
        enabled_tools=frozenset({'get_project_overview'}),
        published_version_id='v-global-1', prepare=prepare, **overrides)


def test_simulation_persists_visible_reply_and_exact_state_receipt(env):
    calls=[]
    out=_run(env, _fake_prepare(env,calls))
    assert out['replayed'] is False and out['delivery']=='in_app_only'
    assert '1. Verified home\n2. Verified apartment' in out['reply']
    assert len(calls)==1
    assert calls[0]['enabled_tools']==frozenset({'get_project_overview'})
    assert env.db.get(env.orm.SalesMessage,out['message_id']).metadata_json['engine']=='hermes-agent'
    assert env.orm.store.load(env.db,SCOPE).revision==1
    event=env.db.query(env.orm.models.HermesSalesStateEvent).one()
    assert event.event_key=='hermes:sim:inbound-a'


def test_retry_returns_exact_original_reply_without_reinvoking_model(env):
    calls=[]
    first=_run(env,_fake_prepare(env,calls))
    second=_run(env,lambda *_a,**_kw:pytest.fail('SDK must not run on replay'))
    assert second['replayed'] is True
    assert second['reply']==first['reply']
    assert second['message_id']==first['message_id']
    assert len(calls)==1
    assert env.db.query(env.orm.SalesMessage).filter_by(direction='outbound').count()==4  # 3 fixture outbound + 1 P08


def test_live_sms_or_whatsapp_is_never_accepted(env):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    for channel in ('sms','whatsapp'):
        env.conversation.channel=channel
        with pytest.raises(P08SimulationNotReady,match='simulation'):
            _run(env,lambda *_a,**_kw:pytest.fail('No SDK call on live'))
    assert env.orm.store.load(env.db,SCOPE).revision==0


def test_non_demo_lead_rejected(env):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    env.lead.is_demo=False
    with pytest.raises(P08SimulationNotReady,match='demo'):
        _run(env,lambda *_a,**_kw:pytest.fail('No SDK call'))


@pytest.mark.parametrize('attribute,value',[
    ('is_opt_out',True),('consent_status','unknown'),('agent_status','human_control'),
])
def test_unsafe_lead_state_rejected(env,attribute,value):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    setattr(env.lead,attribute,value)
    with pytest.raises(P08SimulationNotReady):
        _run(env,lambda *_a,**_kw:pytest.fail('No SDK call'))


def test_paused_conversation_is_not_resumeable_from_worker(env):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    env.conversation.is_paused=True
    with pytest.raises(P08SimulationNotReady):
        _run(env,lambda *_a,**_kw:pytest.fail('No SDK call'))


def test_wrong_inbound_ownership_rejected(env):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    env.inbound.metadata_json={'lead_id':'another-lead'}
    with pytest.raises(P08SimulationNotReady,match='attributable'):
        _run(env,lambda *_a,**_kw:pytest.fail('No SDK call'))


def test_sdk_failure_writes_no_reply_or_state(env):
    def broken(*_args,**_kwargs):
        raise RuntimeError('SDK unavailable')
    with pytest.raises(RuntimeError,match='SDK unavailable'):
        _run(env,broken)
    assert env.orm.store.load(env.db,SCOPE).revision==0
    assert env.db.query(env.orm.SalesMessage).filter_by(direction='outbound').count()==3


def test_no_published_version_is_rejected_before_sdk(env):
    from app.modules.hermes_sales_core.p08_simulation import execute_staged_simulation, P08SimulationNotReady
    with pytest.raises(P08SimulationNotReady,match='published'):
        execute_staged_simulation(env.db,SCOPE,inbound_message_id='inbound-a',
            settings=object(), enabled_tools=frozenset(), published_version_id='',
            prepare=lambda *_a,**_kw:pytest.fail('Should not prepare'))


def test_outbound_without_state_receipt_requires_review(env):
    from app.modules.hermes_sales_core.p08_simulation import P08SimulationNotReady
    env.db.add(env.orm.SalesMessage(id='orphan-p08',conversation_id=SCOPE.conversation_id,
        direction='outbound',channel='simulation',role='assistant',status='sent',content='Not committed',
        metadata_json={'lead_id':SCOPE.lead_id,'hermes_inbound_message_id':'inbound-a','engine':'hermes-agent'}))
    env.db.commit()
    with pytest.raises(P08SimulationNotReady,match='manual review'):
        _run(env,lambda *_a,**_kw:pytest.fail('Never rerun after partial output'))
