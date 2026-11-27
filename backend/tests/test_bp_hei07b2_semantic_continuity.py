"""Offline unit contracts: no inference, network, storage or database writes."""
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from app.modules.hermes_sales_core.sdk_diagnostics import evidence, response_failure, read_evidence, HEADER, BUSY_DETAIL, REVIEW_DETAIL
from app.modules.hermes_sales_core.semantic_material import discover, safe_read_only_fallback, align_contextual_search


@pytest.mark.parametrize('status,detail,expected', [
    (409, BUSY_DETAIL, 'SDK_BUSY'), (409, REVIEW_DETAIL, 'SDK_PREPARATION_REVIEW'),
    (409, 'other', 'SDK_PREPARATION_REVIEW'), (401, BUSY_DETAIL, 'SDK_AUTHORIZATION_FAILED'),
    (403, None, 'SDK_AUTHORIZATION_FAILED'), (503, BUSY_DETAIL, 'SDK_NOT_READY'),
    (500, None, 'SDK_HTTP_ERROR'), (422, None, 'SDK_HTTP_ERROR'),
])
def test_only_exact_busy_is_safe_to_retry(status, detail, expected):
    r=httpx.Response(status,json={'detail':detail})
    assert response_failure(r)=={'sdk_http_status':status,'sdk_error_code':expected}


def test_remote_evidence_does_not_include_raw_exception_or_body():
    try:
        raise ValueError('secret token or buyer message')
    except ValueError as exc:
        diagnostic=evidence(exc,'validate_reply')
    diagnostic['raw']='secret token'
    r=httpx.Response(409,json={'detail':REVIEW_DETAIL,'other':'secret'},headers={HEADER:json.dumps(diagnostic)})
    result=response_failure(r)
    assert result['sdk_failure']['checkpoint']=='validate_reply'
    assert result['sdk_failure']['exception_type']=='ValueError'
    assert 'secret' not in str(result).replace('test_remote_evidence_does_not_include_raw_exception_or_body','')
    assert result['sdk_failure']['locations']


@pytest.mark.parametrize('raw', [None,'x','[]','{'+'x'*2100])
def test_bad_diagnostic_header(raw):
    assert read_evidence(raw)=={}


def port(message='Do you have blueprints?', verified=None):
    if verified is None:
        verified={'brochure':[{'asset_id':'brochure','name':'Cleveland brochure'}],
                  'gallery_image':[{'asset_id':'gallery','name':'Cleveland gallery'}]}
    p=SimpleNamespace(message=message,inbound_id='turn',state={'offered_assets':{},'conversation_focus':{'property_type_id':'cleveland'}},
                      semantic_media_discovery=None,search_batches=[],slot_batches=[],comparison_batches=[],menus=[],prepared_visit=None,offered_media=None)
    p._assets=lambda args: {'ok':True,'assets_by_subject':verified,'assets':list(verified),'unit_id':'cleveland','display_name':'Cleveland'}
    return p


@pytest.mark.parametrize('text', ['Do you have blueprints?','Can I see its architectural drawings?','What other documents are available?'])
def test_semantic_query_returns_approved_categories_without_share(text):
    p=port(text); initial=deepcopy(p.state)
    result=discover(p,{}, {'error_code':'MEDIA_TYPE_REQUIRED'}, {},explicit_tags=[])
    assert result['ok'] and result['delivery']=='not_sent' and result['share_issued'] is False
    assert result['assets']==[] and set(result['available_subjects'])=={'brochure','gallery_image'}
    assert 'floor_plan' not in result['assets_by_subject'] and p.state==initial
    assert 'a brochure' in safe_read_only_fallback(p,initial,sources=['turn'],primary_snapshot=None)


def test_no_match_is_not_a_match_and_never_substitutes():
    p=port('Do you have a floor plan?')
    result=discover(p,{}, {'ok':True,'delivery':'unavailable','assets':[]}, {},explicit_tags=['floor_plan'])
    assert result['delivery']=='unavailable' and result['assets']==[]
    assert result['assets_by_subject']['brochure'] and 'floor_plan' not in result['assets_by_subject']


def test_explicit_media_delivery_contract_is_unchanged():
    p=port('Send me the brochure');pending={'source_inbound_message_id':'turn','subject':'brochure','asset_ids':['brochure']}
    p.state['offered_assets']={'pending_request':pending}
    expected={'ok':True,'assets':[{'asset_id':'brochure'}],'delivery':'pending_backend_share'}
    assert discover(p,{},expected,{},explicit_tags=['brochure']) is expected
    assert p.state['offered_assets']['pending_request']==pending


@pytest.mark.parametrize('text', ['Yes, please','Send the document'])
def test_unsupported_share_is_not_sent_as_another_type(text):
    p=port(text);prior={'presented_offer':{'subject':'brochure'}}
    p.state['offered_assets']={'pending_request':{'source_inbound_message_id':'turn','subject':'brochure','asset_ids':['brochure']}}
    result=discover(p,{}, {'ok':True,'delivery':'pending_backend_share'}, prior,explicit_tags=[])
    assert p.state['offered_assets']==prior and result['share_issued'] is False


def test_approved_single_pdf_lane_is_unchanged():
    p=port('Please send the PDF');p.state['offered_assets']={'pending_request':{'source_inbound_message_id':'turn','subject':'brochure','asset_ids':['brochure']}}
    outcome={'ok':True,'delivery':'pending_backend_share'}
    assert discover(p,{},outcome,{},explicit_tags=[]) is outcome


@pytest.mark.parametrize('mutation',['search_batches','slot_batches','comparison_batches','menus','prepared_visit','visit_draft','search_preferences','pending_request'])
def test_fallback_does_not_mask_other_operations(mutation):
    p=port();initial=deepcopy(p.state)
    discover(p,{}, {'error_code':'MEDIA_TYPE_REQUIRED'}, {},explicit_tags=[])
    if mutation=='pending_request':p.state['offered_assets']={'pending_request':{'source_inbound_message_id':'turn'}}
    elif mutation in {'visit_draft','search_preferences'}:p.state[mutation]={'changed':True}
    else:setattr(p,mutation,[{'x':1}])
    assert safe_read_only_fallback(p,initial,sources=['turn'],primary_snapshot=None) is None


def test_primary_scope_only_for_exact_evidenced_search():
    p=port();p.contextual_preference={'bedrooms':{'preferred':3}}
    p.state['search_preferences']={'last_source_message_id':'turn'}
    p.state['active_search']={'criteria':{'bedrooms':3},'source_inbound_message_id':'turn','scope':'temporary'}
    assert align_contextual_search(p,{'ok':True,'search_scope':'temporary'})['search_scope']=='permanent'
    p.state['active_search']['criteria']={'bedrooms':4};p.state['active_search']['scope']='temporary'
    assert align_contextual_search(p,{'ok':True,'search_scope':'temporary'})['search_scope']=='temporary'
