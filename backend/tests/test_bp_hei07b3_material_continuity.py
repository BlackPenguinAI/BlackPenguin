"""HEI-07B.3.1: pure presentation/privacy and scoped recovery contracts."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.hermes_sales_core.material_continuity import (
    MATERIALS, REDACTED, composition, continuation_question, has_private_link,
    redact, render_delivery,
)
from app.modules.hermes_sales_core.live_domain_parity import contextual_bedrooms
from app.modules.hermes_sales_core.semantic_material import (
    read_only_recovery_allowed, safe_read_only_fallback,
)
from app.modules.hermes_sales_core.live_materials import material_message
from app.modules.hermes_sales_core.production_tools import ProductionToolError


@pytest.mark.parametrize('link', [
    'https://example.invalid/api/v1/projects/a/private-token',
    '/api/v1/projects/a/private-token',
    'https://example.invalid/API/v1/PROJECTS/A/private-token?x=123',
    'https://example.invalid/api/v1/projects/a/private-token#fragment',
])
def test_model_projection_never_reuses_private_bearer(link):
    history=[{'role':'assistant','content':'Van Buren gallery\n'+link},
             {'role':'user','content':'Do you have blueprints?'}]
    context={'history':history,'nested':{'url':link,'asset':'Van Buren gallery'}}
    original=deepcopy(context)
    result=redact(context)
    assert 'private-token' not in str(result)
    assert REDACTED in str(result)
    assert result['history'][1]['content']=='Do you have blueprints?'
    assert result['nested']['asset']=='Van Buren gallery'
    assert context==original and has_private_link(link)


def test_non_private_location_link_is_unchanged():
    assert redact('https://maps.example.invalid/location')=='https://maps.example.invalid/location'


def test_composition_preserves_native_commercial_question_after_real_link():
    template=f"Here's the photo gallery for Van Buren.\n\n{MATERIALS}\n\nWould you like to see the brochure as well?"
    url='https://example.invalid/api/v1/projects/a/issued-test-token'
    text=material_message([{'url':url,'name':'Van Buren gallery'}],{'template':template})
    assert composition(template)==template
    assert text.startswith("Here's the photo gallery for Van Buren.")
    assert text.endswith('Would you like to see the brochure as well?')
    assert text.count(url)==1 and MATERIALS not in text
    assert text.index(url)<text.index('Would you like')


@pytest.mark.parametrize('text', [
    f'Here is the gallery.\n{MATERIALS}\nhttps://foreign.invalid/evil',
    f'Here is the gallery.\n{MATERIALS}\n{MATERIALS}',
    f'Here is {MATERIALS} inline.',
    f'Here is the gallery.\n{MATERIALS}\nThe visit is booked.',
    f'Here is the gallery.\n{MATERIALS}\n{REDACTED}',
    f'{MATERIALS}',
])
def test_invalid_model_template_cannot_insert_arbitrary_links_or_marker(text):
    assert composition(text) is None
    assert render_delivery('approved only',{'template':text})=='approved only'


def test_legacy_reply_retains_only_the_optional_question():
    text='I found a matching resource. Would you like more details about Van Buren?'
    question=continuation_question(text)
    assert question=='Would you like more details about Van Buren?'
    assert render_delivery('approved only',{'question':question})=='approved only\n\n'+question
    assert continuation_question('Could you open https://foreign.invalid/?') is None


def test_legacy_material_output_remains_identical_without_model_copy():
    url='https://example.invalid/api/v1/projects/a/issued-test-token'
    assert material_message([{'url':url,'name':'Van Buren gallery'}])==(
        'Here are the requested approved materials:\n1. Van Buren gallery\n'+url)


def test_invalid_native_url_is_still_rejected():
    with pytest.raises(ProductionToolError):
        material_message([{'url':'https://foreign.invalid/unapproved','name':'Gallery'}],
                         {'question':'Would you like more details?'})


def _port(verified=None):
    state={'offered_assets':{},'conversation_focus':{'property_type_id':'van-buren'}}
    return SimpleNamespace(state=state,inbound_id='current',semantic_media_discovery=verified,
        search_batches=[],slot_batches=[],comparison_batches=[],menus=[],prepared_visit=None,offered_media=None)


def test_link_recovery_after_blueprints_discovery_does_not_relabel_brochure():
    p=_port({'brochure':[{'asset_id':'b','name':'Van Buren brochure'}]})
    initial=deepcopy(p.state)
    result=safe_read_only_fallback(p,initial,sources=['current'],primary_snapshot=None)
    assert 'a brochure' in result and 'floor plan' not in result
    assert '/projects/a/' not in result and p.state==initial


@pytest.mark.parametrize('mutation', ['pending_request','preferences','booking','search','resume'])
def test_recovery_refuses_mixed_or_actionable_turns(mutation):
    p=_port({'brochure':[{'asset_id':'b'}]});initial=deepcopy(p.state)
    sources=['current'];primary=None
    if mutation=='pending_request':p.state['offered_assets']['pending_request']={'source_inbound_message_id':'current'}
    elif mutation=='preferences':primary={'revision':1}
    elif mutation=='booking':p.state['confirmation_request']={'status':'execution_requested'}
    elif mutation=='search':p.search_batches=[{'rows':[]}]
    else:sources=['earlier','current']
    assert not read_only_recovery_allowed(p,initial,sources=sources,primary_snapshot=primary)
    assert safe_read_only_fallback(p,initial,sources=sources,primary_snapshot=primary) is None


def test_metadata_recovery_requires_verified_catalog():
    p=_port();initial=deepcopy(p.state)
    assert read_only_recovery_allowed(p,initial,sources=['current'],primary_snapshot=None)
    assert safe_read_only_fallback(p,initial,sources=['current'],primary_snapshot=None) is None


def test_observed_buyer_acceptance_after_open_no_match_question():
    prior={'active_search':{'criteria':{'bedrooms':2},'match_count':0},
           'search_preferences':{'bedrooms':{'mode':'preferred','preferred':2}}}
    previous=('There are currently no verified 2-bedroom houses available in Cedar Ridge at Sterling Ranch.\n\n'
              "If you're open to adjustments, would you like to explore listings with a different number of bedrooms or other features?")
    assert contextual_bedrooms('Yes, 3 bedrooms it’s ok',prior,previous)=={'bedrooms':{'mode':'preferred','preferred':3}}
    assert not contextual_bedrooms('Show me other 3-bedroom houses',prior,previous)
    assert not contextual_bedrooms('Yes, 3 bedrooms it’s ok',prior,'Would you like to explore 4-bedroom houses?')
    assert not contextual_bedrooms('Yes, 3 bedrooms it’s ok',{**prior,'active_search':{'match_count':1}},previous)


def test_shared_material_context_contains_only_current_approved_metadata():
    from app.modules.hermes_sales_core.material_continuity import shared_materials
    state={'a':{'share_id':'private-receipt','source_message_id':'previous'},
           'withdrawn':{'share_id':'withdrawn-receipt'}}
    assets=[{'asset_id':'a','name':'Van Buren gallery','content_tags':['gallery_image'],
             'url':'https://example.invalid/api/v1/projects/a/private-token'},
            {'asset_id':'b','name':'Unshared brochure','asset_type':'brochure'}]
    assert shared_materials(state,assets)==[{'asset_id':'a','name':'Van Buren gallery',
        'subjects':['gallery_image'],'status':'provider_accepted'}]


def test_read_only_recovery_keeps_verified_property_name():
    p=_port({'gallery_image':[{'asset_id':'g'}]});p.semantic_media_property_name='Van Buren'
    text=safe_read_only_fallback(p,deepcopy(p.state),sources=['current'],primary_snapshot=None)
    assert 'Van Buren' in text and 'a photo gallery' in text
