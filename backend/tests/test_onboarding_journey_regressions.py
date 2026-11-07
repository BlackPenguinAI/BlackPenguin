"""Screenshot-driven onboarding regressions. No providers or production writes."""
from uuid import uuid4
from unittest.mock import patch
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects import services
from app.modules.projects.editor_tasks import detect_task
from app.modules.projects.router import _next_question
from app.modules.projects.meta_oauth_return import oauth_return
from app.modules.company_onboarding.source_service import _corporate_social_profile


def test_inventory_intent_and_legacy_shortcut_are_actions():
    assert detect_task('Open review: catalog') == 'catalog'
    assert detect_task("Okay, let's fill in available inventory") == 'catalog'
    assert detect_task('I want to approve the company profile') == 'review'
    assert detect_task('Bank financing') is None


def test_catalog_shortcut_resumes_deferred_card(api):
    client, (_, _, _, project, profile, _) = api
    profile.field_sources = {'__ui_deferrals__': {'field:property_type_catalog': {'deferred': True, 'draft': {'answer':'Preserved draft'}}}}
    response = client.post(f'/projects/{project.id}/editor/catalog', json={'message':'Open review: catalog','client_message_id':str(uuid4())})
    assert response.status_code == 200, response.text
    assert response.json()['next_question']['input_type'] == 'property_type_catalog'
    assert not response.json()['profile']['ui_deferrals']['field:property_type_catalog']['deferred']
    assert response.json()['profile']['ui_deferrals']['field:property_type_catalog']['draft']['answer'] == 'Preserved draft'


def test_inventory_question_explains_why_catalog_confirmation_is_not_enough(context):
    _, _, _, _, profile, _ = context
    with patch('app.modules.projects.router.services.serialize_profile', return_value={'completion':{'blockers':[{'field':'available_inventory','label':'Available inventory','status':'missing','requirement':'required'}]}}):
        question = _next_question(profile)
    assert question['label'] == 'Confirm current availability'
    assert 'Unknown is not zero' in question['prompt']


def test_oauth_return_redirects_same_tab_without_exposing_code():
    response = oauth_return('https://blackpenguin.ai',state='nonce',project_id='project-1',connected=True)
    assert 'window.location.replace' in response.body.decode()
    assert 'meta_oauth=connected' in response.body.decode()
    assert response.headers['cache-control'] == 'no-store'


def test_social_posts_are_not_corporate_profiles():
    assert _corporate_social_profile('https://www.instagram.com/cheshomes/')
    assert not _corporate_social_profile('https://www.instagram.com/p/123/')
    assert not _corporate_social_profile('https://www.facebook.com/company/posts/123/')


def test_overview_deduplicates_city_and_region_components():
    assert services.overview_address('2968 Weston Loop, Virginia Beach, VA 23456','Virginia Beach, Virginia','US') == '2968 Weston Loop, Virginia Beach, VA 23456, US'


def test_extracted_area_unit_matches_the_form_without_converting_numbers():
    from app.modules.projects.source_service import _catalog_area_unit
    assert _catalog_area_unit('sqft') == 'ft²'
    assert _catalog_area_unit('square feet') == 'ft²'
    assert _catalog_area_unit('m²') == 'm²'
    assert _catalog_area_unit(None) is None
