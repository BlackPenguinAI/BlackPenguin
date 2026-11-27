"""Supplemental evidence privacy and completeness checks."""
from xml.etree import ElementTree as ET
import json
from lifecycle_evidence import PROPERTY, LifecycleEvidence, parse_lifecycle, state_shape, reply_shape


def xml_case(value):
    case=ET.Element('testcase');props=ET.SubElement(case,'properties')
    ET.SubElement(props,'property',name=PROPERTY,value=value)
    return case


def test_stage_shapes_distinguish_capture_from_receipt():
    state={'search_preferences':{'revision':1,'budget':{'maximum_usd':350000},'bedrooms':{'mode':'exact','preferred':3},'last_source_message_id':'secret-inbound'},
           'last_presented_choice_set':{'type':'visit_day','display_name':'Van Buren','unit_id':'secret-unit','source_reply_message_id':'secret-reply','proposal_id':'secret-proposal','options':[{},{}]},
           'last_slot_search':{'unit_id':'secret-unit','proposal_id':'secret-proposal','source_reply_message_id':'secret-reply'}}
    e=LifecycleEvidence();e.add('before_sdk',**state_shape(state,'secret-inbound'));e.add('outbound',**reply_shape('No verified matches. https://example.invalid/private'))
    e.tools('sdk_tool',[{'tool':'select_visit_time','status':'rejected','error_code':'VISIT_SELECTION_ALREADY_RESOLVED','args':{'private':'secret'}}])
    parsed=parse_lifecycle(xml_case(e.serialized()));assert parsed['status']=='RECORDED'
    assert parsed['events'][0]['primary_budget_350k'] and parsed['events'][0]['menu_display_name_bound']
    assert parsed['events'][0]['primary_source_current'] and parsed['events'][0]['offer_matches_menu']
    assert parsed['events'][1]['no_match_text'] and parsed['events'][2]['error_code']=='VISIT_SELECTION_ALREADY_RESOLVED'
    assert 'secret' not in json.dumps(parsed) and 'https://' not in json.dumps(parsed)


def test_untrusted_extra_keys_and_values_are_not_exported():
    data={'events':[{'stage':'sdk_tool','tool':'token-private','status':'private-status','error_code':'token-private','raw':'secret','menu_options':'secret','primary_has_source':'secret'},
                    {'stage':'failure','failure_type':'private-error','failure_function':'secret-function','failure_line':200000,'failure_reason':'https://secret'}]}
    result=parse_lifecycle(xml_case(json.dumps(data)));serialized=json.dumps(result)
    assert result['status']=='RECORDED' and result['events'][0]['tool']=='unknown'
    assert all(x not in serialized for x in ('private','secret','https://','200000'))


def test_invalid_trace_is_never_treated_as_recorded():
    assert parse_lifecycle(xml_case('{bad json'))['status']=='MISSING_OR_INVALID'
    assert parse_lifecycle(xml_case(json.dumps({'events':[{'stage':'raw_secret'}]})))['status']=='MISSING_OR_INVALID'
    assert parse_lifecycle(xml_case(json.dumps({'events':[]})))['status']=='MISSING_OR_INVALID'
