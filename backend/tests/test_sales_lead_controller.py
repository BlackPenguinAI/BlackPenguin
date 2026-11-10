"""Driver reliability is independent from sales quality; no external model calls."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from tools.sales_ai.lead_controller import ControlledLead, role_error, metrics
import json


def output(retry='Could you tell me more?',next_message='How many bedrooms?',status='pending',evidence=''):
    return json.dumps({'response_status':status,'response_evidence':evidence,
                       'retry_message':retry,'next_message':next_message})


def transcript(rows=()):
    return {'initial_agent_reply':'Hello, how can I help?',
            'turns':[{'lead':lead,'agent':agent} for lead,agent in rows]}


def step(c,raw,rows=(),finalize=False):
    infer=AsyncMock(return_value=raw)
    result=asyncio.run(c.next('not-a-key','test/offline',transcript(rows),finalize=finalize,infer=infer))
    return result,infer


@pytest.mark.parametrize('draft',[
    'The Ridge Townhome has 3 bedrooms and covers 165 m². Is there anything else you would like to know?',
    'How can I help you with your property search?',
    'Would you like me to send you the brochure?',
    'Here are our available properties.',
    'Our homes start at 500000 USD.',
    'The Ridge Townhome has 3 bedrooms and covers 165 m².',
    'Can I help you choose a property?',
])
def test_seller_drafts_are_never_delivered(draft):
    c=ControlledLead({'scenario':'continuity','property_interest':'Ridge Townhome'})
    result,_=step(c,output(draft))
    assert result['message']!=draft and not role_error(result['message'])
    assert c.events[0]['reason']=='seller_role'
    assert result['controller']['draft_source']=='controller_fallback'


@pytest.mark.parametrize('draft',[
    'What is the price and current availability of the Ridge Townhome?',
    'I have cash available.',
    'No, I prefer to continue here. How many bedrooms does it have?',
    'Yes, please send the brochure you offered.',
])
def test_customer_messages_are_allowed(draft):
    assert role_error(draft) is None


def test_persistent_nonanswer_gets_at_most_two_attempts_per_goal_and_never_passes():
    c=ControlledLead({'scenario':'continuity','property_interest':'Ridge Townhome'})
    rows=[]
    for _ in range(6):
        result,_=step(c,output('Tell me more'),rows)
        assert not result['done']
        rows.append((result['message'],'Which property option do you mean?'))
    result,_=step(c,output(),rows,finalize=True)
    assert result['done'] and c.finished and not c.resolved
    assert len(c.sent)==6
    assert [r['attempts'] for r in c.records]==[2,2,2]
    assert all(r['outcome']=='unresolved' for r in c.records)


def test_repeat_is_blocked_but_a_single_bounded_clarification_remains_possible():
    c=ControlledLead({'scenario':'targeted_materials','property_interest':'Ridge Townhome'})
    first,_=step(c,output('Please send photos of Ridge Townhome'))
    second,_=step(c,output('Please send photos of Ridge Townhome'),[(first['message'],'Which property do you mean?')])
    assert second['message']!=first['message']
    assert c.events[-2]['reason']=='repeated_message'
    assert second['controller']['goal_attempt']==2


def test_answer_moves_on_and_does_not_depend_on_a_driver_done_boolean():
    c=ControlledLead({'scenario':'targeted_materials','property_interest':'Bay Residence'})
    first,_=step(c,output('Please send photos and PDF for Bay Residence'))
    reply='Bay Residence gallery: https://evaluation.invalid/example. No PDF is available.'
    second,_=step(c,output(next_message='Is parking confirmed for Bay Residence?',status='answered',evidence='No PDF is available.'),[(first['message'],reply)])
    assert second['controller']['goal_id']=='parking'
    assert c.records[0]['outcome']=='answered'
    rows=[(first['message'],reply),(second['message'],'Parking is not confirmed.')]
    done,_=step(c,output(status='unavailable',evidence='Parking is not confirmed.'),rows,True)
    assert done['done'] and c.resolved


def test_unknown_is_accepted_without_inventing_missing_materials():
    c=ControlledLead({'scenario':'targeted_materials','property_interest':'Ridge Townhome'})
    first,_=step(c,output('Could you send photos and a PDF for Ridge Townhome?'))
    reply='No gallery or PDF is available for Ridge Townhome.'
    second,_=step(c,output(next_message='Is parking confirmed?',status='unavailable',evidence=reply),[(first['message'],reply)])
    assert c.records[0]['outcome']=='unavailable' and second['controller']['goal_id']=='parking'


def test_fabricated_quote_does_not_advance_or_hide_failure():
    c=ControlledLead({'scenario':'continuity','property_interest':'Summit Villa'})
    first,_=step(c,output('What does Summit Villa cost?'))
    result,_=step(c,output(status='answered',evidence='It costs 620000 USD'),[(first['message'],'Which property do you mean?')])
    assert result['controller']['goal_id']=='price_availability'
    assert any(e['kind']=='rejected_assessment' for e in c.events)


def test_old_quote_is_not_evidence_for_latest_reply():
    c=ControlledLead({'scenario':'continuity'})
    first,_=step(c,output())
    result,_=step(c,output(status='answered',evidence='Price is 460000 USD'),
        [('Earlier question','Price is 460000 USD'),(first['message'],'Could you clarify?')])
    assert result['controller']['goal_id']=='price_availability'


def test_no_forced_third_turn_after_material_and_parking_goals():
    c=ControlledLead({'scenario':'targeted_materials','property_interest':'Bay Residence'})
    a,_=step(c,output())
    b,_=step(c,output(status='answered',evidence='Here are both requested links'),[(a['message'],'Here are both requested links')])
    result,_=step(c,output(status='answered',evidence='Two spaces'),[(a['message'],'Here are both requested links'),(b['message'],'Two spaces')],True)
    assert result['done'] and len(c.sent)==2 and c.finished


def test_qualification_is_conditional_and_no_neighborhood_drift():
    c=ControlledLead({'scenario':'new_buyer','detail_property':'Bay Residence'})
    a,_=step(c,output('Tell me about the neighborhood'))
    assert 'neighborhood' not in a['message']
    b,_=step(c,output(status='answered',evidence='Bay Residence is available',next_message='What floor area does Bay Residence have?'),[(a['message'],'Bay Residence is available')])
    result,_=step(c,output(status='answered',evidence='240 square meters'),[(a['message'],'Bay Residence is available'),(b['message'],'240 square meters')],True)
    assert result['done'] and c.records[-1]['outcome']=='not_requested'


def test_request_contains_visible_transcript_and_synthetic_profile_only():
    c=ControlledLead({'scenario':'continuity','property_interest':'Summit Villa','budget_amount':900000})
    _,infer=step(c,output())
    payload=json.loads(infer.await_args.args[2][1]['content'])
    assert set(payload)=={'initial_agent_reply','turns','controller'}
    assert 'approved_context' not in payload and 'pipeline_trace' not in payload
    schema=infer.await_args.kwargs['response_format']['json_schema']['schema']
    assert 'done' not in schema['properties']
    assert infer.await_args.args[1]=='test/offline'


def test_controller_metrics_do_not_mark_unresolved_goals_as_sales_success():
    c=ControlledLead({'scenario':'continuity'})
    for _ in range(6):step(c,output(),[('Question','No response')])
    step(c,output(),[('Question','No response')],True)
    result=metrics([{'lead_controller':c.audit('goals_exhausted'),'turns':[]}])
    assert result['finished']==1 and result['perceived_resolved_cases']==0
    assert result['unresolved_goals']==3


@pytest.mark.parametrize('draft', [
    'I am considering bank financing. How many bedrooms does it have?',
    'I have cash available. How many bedrooms does it have?',
    'I now prefer bank financing.',
])
def test_payment_change_goal_cannot_be_weakened_or_drop_independent_question(draft):
    c=ControlledLead({'scenario':'continuity','property_interest':'Summit Villa'})
    c.index=2
    result,_=step(c,output(draft))
    assert result['controller']['draft_source']=='controller_fallback'
    assert result['message']=='I now prefer bank financing. How many bedrooms does Summit Villa have?'
    assert any(e.get('reason')=='goal_mismatch' for e in c.events)


def test_assessment_only_does_not_create_an_extra_sales_turn():
    c=ControlledLead({'scenario':'continuity'})
    first,_=step(c,output('What is the price and availability?'))
    result,_=step(c,output(status='answered',evidence='The price is unknown.'),[(first['message'],'The price is unknown.')],True)
    assert result['done'] and len(c.sent)==1
    assert not c.finished and not c.resolved
    assert c.audit('turn_limit')['goals'][-1]['outcome']=='not_exercised'


def test_malformed_driver_contract_fails_closed_without_sending_message():
    c=ControlledLead()
    infer=AsyncMock(return_value='{"message":"Invented answer","done":true}')
    with pytest.raises(ValueError,match='controlled lead contract'):
        asyncio.run(c.next('unused','test/offline',transcript(),infer=infer))
    assert not c.sent


@pytest.mark.parametrize('reply,expected',[
    ('The payment options are cash and financing. What else would you like to know?', 'not_requested'),
    ('The home has 4 bedrooms. What budget range and currency are you considering?', None),
])
def test_conditional_qualification_requires_an_actual_question(reply,expected):
    c=ControlledLead({'scenario':'new_buyer','budget_amount':900000})
    c.index=2
    result,_=step(c,output('My budget is 900000 USD and I can pay cash'),[('Previous question',reply)])
    if expected:
        assert result['done'] and c.records[-1]['outcome']==expected
    else:
        assert not result['done'] and result['controller']['goal_id']=='qualification'
