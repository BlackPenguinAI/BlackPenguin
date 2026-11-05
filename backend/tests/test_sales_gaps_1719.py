"""Independent acceptance probes. No production writes or real providers."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from test_sales_turn_1720 import case, run_live, model_turn, approved_asset, execute_material, outbound
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.live_service import _execute_share_actions
from app.modules.projects.models import SalesAssetShare


def test_visual_request_never_reaches_slot_tools_after_wrong_high_confidence_label(case):
    text="Pictures of the unit at 3 PM please"
    result,_=model_turn(case,text,primary="select_appointment_slot",secondary=["request_visual_material"],confidence=.99,reply="I can help with approved images.")
    assert result["response_policy_trace"]["appointment_intent"] is False
    dispatch,slots,graph,ids=run_live(case,text,result)
    slots.assert_not_called()
    assert "appointment" not in dispatch.await_args.kwargs["content"].lower()


def test_revoked_offer_consent_explains_missing_resource_instead_of_empty_confirmation(case):
    asset=approved_asset(case,["brochure"],name="Previously offered brochure")
    db,company,project,lead,conversation=case
    conversation.pending_asset_id=asset.id
    db.commit()
    outbound(db,conversation,"Would you like this brochure?",{"material_offer":{"asset_ids":[asset.id]}})
    asset.approval_status="draft";db.commit()
    (reply,actions,shares),offer=execute_material(case,"Yes, please",reply="I will share the brochure now.")
    assert not shares
    assert "will share" not in reply
    assert any(word in reply.lower() for word in ("unavailable","no longer","don't currently have","not available"))


def test_verified_virtual_tour_is_not_hidden_after_ten_other_links(case):
    links=[{"url":f"https://example.com/resource/{i}","kind":"external_reference","label":f"Reference {i}"} for i in range(10)]
    tour="https://my.matterport.com/show/?m=generic-verified-tour"
    links.append({"url":tour,"kind":"virtual_tour","label":"Verified 360 tour"})
    approved_asset(case,["brochure","virtual_tour"],links=links)
    (reply,actions,shares),offer=execute_material(case,"Please send the 360 virtual tour.")
    db,*_=case
    assert tour in [row.target_url for row in db.query(SalesAssetShare).all()]


@pytest.mark.parametrize("reason",["draft","expired","channel"])
def test_offer_revalidation_explains_all_unavailable_states(case,reason):
    asset=approved_asset(case,["brochure"])
    db,company,project,lead,conversation=case
    conversation.pending_asset_id=asset.id;db.commit()
    outbound(db,conversation,"Would you like the brochure?",{"material_offer":{"asset_ids":[asset.id]}})
    if reason=="draft":asset.approval_status="draft"
    elif reason=="expired":asset.valid_until=datetime.utcnow()-timedelta(seconds=1)
    else:asset.allowed_channels=["whatsapp"]
    db.commit()
    (reply,actions,shares),offer=execute_material(case,"Yes, please",reply="I will send it now.")
    assert not shares and "no longer" in reply and "will send" not in reply
    assert conversation.pending_asset_id is None


def test_partial_revocation_shares_only_remaining_offered_resources(case):
    first=approved_asset(case,["brochure"],name="Revoked file")
    second=approved_asset(case,["brochure"],name="Still approved file")
    db,company,project,lead,conversation=case
    conversation.pending_asset_id=first.id;db.commit()
    outbound(db,conversation,"Would you like both?",{"material_offer":{"asset_ids":[first.id,second.id]}})
    first.approval_status="draft";db.commit()
    (reply,actions,shares),offer=execute_material(case,"Yes, please")
    assert len(shares)==1 and "Still approved file: http" in reply
    assert "Revoked file: http" not in reply and "no longer" in reply


def test_link_list_preserves_late_tour_but_rejects_unsafe_urls(case):
    links=[{"url":f"https://example.com/{i}","kind":"external_reference"} for i in range(15)]
    links += [{"url":"https://my.matterport.com/show/?m=late-tour","kind":"virtual_tour"},
              {"url":"http://127.0.0.1/private","kind":"virtual_tour"},
              {"url":"https://user:secret@example.com/tour","kind":"virtual_tour"}]
    approved_asset(case,["virtual_tour"],links=links)
    db,company,project,lead,conversation=case
    context=build_commercial_context(db,project=project,company_id=company.id,lead_id=lead.id)
    urls=[link["url"] for link in context["available_assets"][0]["links"]]
    assert len(urls)==16 and not any("127.0.0.1" in url or "secret" in url for url in urls)
