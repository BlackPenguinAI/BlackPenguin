"""Full backend replay of the provider output from closing-point."""
import json
from tools.sales_ai.p1a_price_comparison_selftest import MESSAGE, RECORDED, CATALOG
from app.modules.sales_agent.interpretation_input import compile_input
from app.modules.sales_agent.mixed_human_pricing import verified_mixed_price_read


def test_recorded_output_compiles_to_scoped_pricing_read_without_confidence_promotion():
    interpreted, notes = compile_input(json.dumps(RECORDED), MESSAGE, approved_names=['Bay Residence'])
    assert interpreted.visit is None
    assert interpreted.comparison is None
    assert interpreted.confidence == 0
    assert not interpreted.requires_clarification
    assert len(interpreted.requests) == 1
    assert interpreted.requests[0].topic.value == 'pricing'
    assert interpreted.requests[0].evidence == 'What is the price of Bay Residence?'
    assert len(interpreted.references) == 1
    assert interpreted.references[0].kind == 'property'
    assert interpreted.references[0].expression == 'Bay Residence'
    assert any(n['action']=='omit_human_contact_misread_as_visit' for n in notes)
    assert any(n['action']=='single_price_question_not_comparison' for n in notes)
    assert verified_mixed_price_read(interpreted, MESSAGE, CATALOG, human_step='ask')
    assert not verified_mixed_price_read(interpreted, MESSAGE, CATALOG, human_step='record')
    assert not verified_mixed_price_read(interpreted, MESSAGE, CATALOG, human_step='ask',holds={'pricing'})
