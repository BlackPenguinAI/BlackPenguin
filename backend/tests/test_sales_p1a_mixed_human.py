"""Recorded closing-point malformed model output must preserve pricing.

This contract test requires normal backend dependencies but no model, DB or
network access. Only a negative visit correction is allowed.
"""
import json
from app.modules.sales_agent.interpretation_input import compile_input
from tools.sales_ai.p1a_mixed_human_selftest import MIXED, RECORDED


def test_real_wire_compiler_preserves_mixed_human_pricing():
    raw=json.dumps(RECORDED)
    interpreted, notes=compile_input(raw,MIXED,approved_names=['Bay Residence','Cedar Studio'])
    assert interpreted.visit is None
    assert not interpreted.requires_clarification
    assert interpreted.permits('pricing')
    assert len(interpreted.requests)==1
    assert interpreted.requests[0].topic.value=='pricing'
    assert len(interpreted.references)==1
    assert interpreted.references[0].expression=='Bay Residence'
    assert any(note.get('action')=='omit_human_contact_misread_as_visit' for note in notes)
