import json,pytest
from app.modules.sales_agent.context_budget import compact,size,INITIAL_BYTES,TOTAL_BYTES,REPAIR_BYTES

@pytest.mark.parametrize('count',[20,50,100])
def test_accumulated_history_preserves_current_state_and_repair_reserve(count):
    state={'selected_property_type_id':'approved','constraints':[{'topic':'appointment','evidence':'No visits yet'}],'booking_proposal':{'id':'exact'}}
    payload={'current_message':'I am looking for a 2 bedroom','turn_context':state,'history':[{'role':'user','content':'Past request '*100} for _ in range(count)],'approved_context':{'property_types':[{'id':str(i),'property_type':f'Home {i}','description':'details '*3000} for i in range(10)]}}
    messages=[{'role':'system','content':'Rules '*1800},{'role':'user','content':json.dumps(payload)}]
    result,trace=compact(messages)
    assert size(result)<=INITIAL_BYTES and size(result)+REPAIR_BYTES<=TOTAL_BYTES
    after=json.loads(result[1]['content']);assert after['turn_context']==state and after['current_message']==payload['current_message']
    assert payload['approved_context']['property_types'][0]['description']
    assert after['approved_context']['property_types'][0]['id']=='0'
    assert len(after['history'])<=count and trace['before_bytes']>trace['after_bytes']


def test_required_state_is_never_silently_truncated():
    with pytest.raises(ValueError):compact([{'content':'Rules'},{'content':json.dumps({'turn_context':{'constraints':['x'*100000]},'history':[]})}])

@pytest.mark.parametrize('text',['Hi','Hello!','I am looking for a 2 bedroom','I am looking for a 3 bedroom home.'])
def test_current_literal_message_cannot_replay_old_visit(text):
    from pathlib import Path
    from app.modules.sales_agent.interpretation_input import compile_input
    rows=json.loads((Path(__file__).parent/'fixtures/sales_context_replay/server_frames.json').read_text())['cases']
    raw=json.loads(rows[0]['turns'][0]['interpretation_attempts'][-1]['raw_response'])
    raw['visit']={'action':'request','evidence':'Old visit request','timing':None}
    raw['preferences']=[]
    result,notes=compile_input(json.dumps(raw),text)
    assert result.visit is None and result.comparison is None and notes
    assert not any(q.topic.value=='appointment' for q in result.requests)
