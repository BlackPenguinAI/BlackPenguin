"""P2-B.2 CI: pure counterfactuals plus SQLite-scoped planner regression."""
import json
import time
from unittest.mock import patch

import pytest

from test_sales_booking_pilot import lab  # noqa: F401 (synthetic SQLite fixture)
from tools.sales_ai.p2b2_mixed_price_selftest import TestP2B2MixedPriceEquivalence  # noqa: F401
from tools.sales_ai.p2b2_mixed_price_equivalence import CASES, REPAIR, input_document
from tools.sales_ai.p2b_repair_ablation import noop
from app.modules.sales_agent.interpretation_input import compile_input
from app.modules.sales_agent.dialogue_store import Scope,load
from app.modules.sales_agent.turn_planner import run as plan_turn
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_crm.models import Lead, Meeting


@pytest.mark.parametrize('without_repair',[False,True],ids=['repaired_price','ablated_comparison'])
def test_real_planner_exposes_loss_of_price_read_in_isolated_sqlite(lab,without_repair):
    """Actual planner in prepare-only mode; no provider, model, calendar or send.

    A v3 one-member price comparison is a valid *provider* packet. Removing the
    repair changes a priced property read to a comparison task even though both
    interpretations pass Pydantic and current-message evidence validation.
    """
    db,manifest=lab
    assert db.get_bind().dialect.name=='sqlite' and manifest['synthetic_only']
    project=manifest['projects'][0]
    case=next(c for c in CASES if c.code=='v3_one_property_price_misread')
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],
              full_name='P2B2 synthetic buyer',phone='+15550922222',
              platform='evaluation',is_demo=True,is_test=True,
              preferred_channel='simulation',consent_status='granted_simulation',
              agent_status='simulation')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=lead.company_id,project_id=lead.project_id,
                                   lead_id=lead.id,channel='simulation',provider='simulation',
                                   is_paused=False)
    db.add(conversation);db.flush()
    message=SalesMessage(conversation_id=conversation.id,channel='simulation',
                         direction='inbound',role='user',status='received',
                         content=case.text,metadata_json={'lead_id':lead.id})
    db.add(message);db.commit()
    opts={'approved_names':case.approved_names}
    if without_repair:
        with patch(REPAIR,side_effect=noop):
            u,_=compile_input(input_document(case),case.text,**opts)
    else:
        u,_=compile_input(input_document(case),case.text,**opts)
    u.check_evidence(case.text)
    scope=Scope(lead.company_id,lead.project_id,conversation.id,lead.id)
    revision,_=load(db,scope)
    outcome=plan_turn(db,scope,message_id=message.id,understanding=u,
                      expected_revision=revision,
                      event_key='p2b2-prepare-'+message.id,max_steps=8,
                      max_seconds=10,max_rounds=1,max_read_units=10,
                      clock=time.monotonic,prepare_only=True)
    current=[t for t in outcome.state.tasks if t.source_message_id==message.id]
    assert len(current)==1
    if without_repair:
        assert u.comparison is not None
        assert current[0].topic.value=='catalog'
        assert current[0].blocked_reason=='comparison_requires_current_request'
        assert not u.permits('pricing')
    else:
        assert u.comparison is None
        assert current[0].topic.value=='pricing'
        assert u.permits('pricing')
        assert current[0].binding_status=='resolved'
    assert not any(t.topic.value in {'appointment','human','opt_out'} for t in current)
    assert outcome.plan['external_actions']==0
    assert outcome.plan['tool_calls']==0
    assert not outcome.plan['write_candidates_require_backend_authorization']
    assert db.query(Meeting).count()==0
