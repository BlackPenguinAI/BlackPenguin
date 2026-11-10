"""Final approval binds the submitted revision after locking the current draft."""
from copy import deepcopy
import pytest
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects import services
from app.modules.projects.models import SenderType


def edit_profile(db, project, user, name='Updated project'):
    profile = services.get_profile(project)
    services.apply_field_updates(db, profile, [
        {'field':'project_name','value':name,'status':'corrected_by_user'}
    ], allow_authoritative_statuses=True, actor_user_id=user.id)
    return profile


def test_stale_tab_cannot_approve_another_sessions_newer_revision(api):
    client, (db, _, user, project, profile, _) = api
    edit_profile(db, project, user)
    expected = profile.draft_revision
    published = deepcopy(profile.published_snapshot)
    edit_profile(db, project, user, 'Other administrator changed this')
    newer = profile.draft_revision
    response = client.post(f'/projects/{project.id}/onboarding/complete',json={'expected_revision':expected})
    assert response.status_code == 409,response.text
    assert response.json()['detail']['code'] == 'onboarding_revision_conflict'
    assert response.json()['detail']['current_revision'] == newer
    db.refresh(profile)
    assert not profile.final_approved and profile.published_snapshot == published


def test_current_revision_approval_publishes_and_redirects_without_rewriting_history(api):
    client, (db, _, user, project, profile, _) = api
    old = services.save_message(db, project.session.id, SenderType.AI, 'Review the older draft',
        ui_payload={'field':None,'label':'Final approval','input_type':'boolean'})
    services.record_message_response(db, project.session.id, old.id, 'I need to make changes',status='accepted')
    before_content, before_time, before_response = old.content, old.created_at, deepcopy(old.response_payload)
    edit_profile(db, project, user)
    response = client.post(f'/projects/{project.id}/onboarding/complete',json={'expected_revision':profile.draft_revision})
    assert response.status_code == 200,response.text
    body = response.json()
    assert body['completed'] and body['redirect_url'] == f'/app/projects/{project.id}'
    assert body['profile']['completion']['final_approved']
    db.refresh(old)
    assert (old.content,old.created_at,old.response_payload) == (before_content,before_time,before_response)


@pytest.mark.parametrize('revision', [-1, True, '2', 1.2])
def test_approval_revision_must_be_a_nonnegative_integer(api, revision):
    client, (_, _, _, project, _, _) = api
    assert client.post(f'/projects/{project.id}/onboarding/complete',json={'expected_revision':revision}).status_code == 422


def test_legacy_empty_body_still_uses_readiness_checks(api):
    client, (_, _, _, project, _, _) = api
    assert client.post(f'/projects/{project.id}/onboarding/complete',json={}).status_code == 200


def test_current_approval_gets_its_own_receipt_not_an_acceptance_on_an_old_pending_card(api):
    from app.modules.projects.models import ProjectMessage
    client, (db, _, user, project, profile, _) = api
    old = services.save_message(db, project.session.id, SenderType.AI, 'Approval requested before edits',
        ui_payload={'field':None,'label':'Final approval','input_type':'boolean'})
    old_time = old.created_at
    edit_profile(db, project, user)
    response = client.post(f'/projects/{project.id}/onboarding/complete',json={'expected_revision':profile.draft_revision})
    assert response.status_code == 200,response.text
    db.refresh(old)
    assert old.created_at == old_time and old.content == 'Approval requested before edits'
    assert old.response_payload['status'] == 'superseded'
    assert old.response_payload['selected_option'] != 'Approve profile'
    receipts = db.query(ProjectMessage).filter(ProjectMessage.content.like('Project Profile approved. Published revision:%')).all()
    assert len(receipts) == 1 and receipts[0].id != old.id and not receipts[0].ui_payload
