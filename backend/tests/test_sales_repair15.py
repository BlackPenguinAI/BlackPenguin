import json
from datetime import datetime
from types import SimpleNamespace as N
import pytest
from test_sales_active_integration import understanding
from app.modules.sales_agent.interpretation_input import compile_input
from app.modules.sales_agent.first_booking import normalize_timing

@pytest.mark.parametrize('part,start,end',[('morning','06:00','12:00'),('afternoon','12:00','18:00'),('evening','18:00','24:00'),('night','18:00','24:00')])
def test_source_period_survives_corrupted_model_timing(part,start,end):
    text=f"I would like a visit any {part} in the next seven days; use the property's timezone."
    raw=understanding(text,'appointment').model_dump()
    raw['visit']={'action':'request','evidence':text,'timing':None}
    raw['visit']['timing']={'timezone_evidence':'America/New_York','time_from_evidence':text,'time_until_evidence':text,'time_relation':'evening' if part=='night' else part}
    result,_=compile_input(json.dumps(raw),text)
    prefs=normalize_timing(result,text,N(timezone='America/New_York'),datetime(2026,11,16),{})
    assert prefs['time_from']==start and prefs['time_until']==end and prefs['timezone']=='America/New_York'

@pytest.mark.parametrize('text',["No, it’s ok. Thanks, bye.",'Yes, send the gallery','Bay Residence','Actually I prefer Bay Residence instead.'])
def test_literal_context_does_not_invent_comparison_or_visit(text):
    meta={'material_offer':{'items':[{'binding':{'mime_type':'image/jpeg','type':'gallery_image','name':'Gallery'}}]}}
    raw=understanding(text,'other').model_dump()
    result,_=compile_input(json.dumps(raw),text,previous_reply='Would you like the gallery?',previous_metadata=meta,approved_names=['Bay Residence'])
    assert result.visit is None and result.comparison is None and not result.requires_clarification
    assert result.courtesy or result.requests

@pytest.mark.parametrize('text',['Send me the brochure and explain financing.','Send me the brochure and tell me the mortgage rates and monthly payments.'])
def test_mixed_request_preserves_both_independent_topics(text):
    raw=understanding(text,'financing').model_dump()
    result,_=compile_input(json.dumps(raw),text)
    assert [r.topic.value for r in result.requests]==['materials','financing'] and result.visit is None
