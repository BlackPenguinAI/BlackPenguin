import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.companies.models import Company
from app.modules.projects import meta_oauth_service
from app.modules.projects.models import MetaAuthorization
from app.modules.subscriptions.models import SubscriptionPlan


class FakeMetaClient:
    def __init__(self, responses: dict[str, tuple[int, dict]]):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **_kwargs) -> httpx.Response:
        key = next((suffix for suffix in self.responses if url.endswith(suffix)), None)
        assert key is not None, f"Unexpected Meta request: {url}"
        status_code, payload = self.responses[key]
        return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))


def _authorization(db) -> MetaAuthorization:
    plan = SubscriptionPlan(name="Meta Asset Test", is_active=True)
    company = Company(name="Meta Asset Company", plan=plan, is_active=True)
    db.add_all([plan, company]); db.flush()
    authorization = MetaAuthorization(
        company_id=company.id, meta_user_id="meta-user", meta_user_name="Meta User",
        token_ciphertext="encrypted", status="active",
        scopes=[
            "pages_show_list", "pages_manage_metadata", "pages_manage_ads",
            "leads_retrieval", "ads_read",
        ],
    )
    db.add(authorization); db.commit(); db.refresh(authorization)
    return authorization


def _run_discovery(monkeypatch, responses, *, page_id=None, ad_account_id=None):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    authorization = _authorization(db)
    fake_client = FakeMetaClient(responses)
    monkeypatch.setattr(meta_oauth_service, "_token", lambda _authorization: "user-token")
    monkeypatch.setattr(
        meta_oauth_service.system_settings, "meta_platform_credentials",
        lambda _db: (SimpleNamespace(graph_api_version="v26.0"), "secret"),
    )
    monkeypatch.setattr(meta_oauth_service.httpx, "AsyncClient", lambda **_kwargs: fake_client)
    try:
        return asyncio.run(meta_oauth_service.discover_assets(
            db, company_id=authorization.company_id, authorization_id=authorization.id,
            page_id=page_id, ad_account_id=ad_account_id,
        ))
    finally:
        db.close(); engine.dispose()


def test_lead_form_graph_failure_returns_actionable_leads_access_message(monkeypatch):
    responses = {
        "/me/accounts": (200, {"data": [{"id": "page-1", "name": "Page", "access_token": "page-token"}]}),
        "/me/adaccounts": (200, {"data": [{"id": "act_123", "account_id": "123", "name": "Ads"}]}),
        "/page-1/leadgen_forms": (403, {"error": {
            "message": "Unsupported get request", "type": "GraphMethodException",
            "code": 100, "error_subcode": 33,
        }}),
    }

    with pytest.raises(HTTPException) as captured:
        _run_discovery(monkeypatch, responses, page_id="page-1")

    assert captured.value.status_code == 422
    assert "Leads Access" in captured.value.detail
    assert "reconnect Meta" in captured.value.detail


def test_optional_campaign_failure_preserves_page_and_form_assets(monkeypatch):
    responses = {
        "/me/accounts": (200, {"data": [{"id": "page-1", "name": "Page", "access_token": "page-token"}]}),
        "/me/adaccounts": (200, {"data": [{"id": "act_123", "account_id": "123", "name": "Ads"}]}),
        "/page-1/leadgen_forms": (200, {"data": [{"id": "form-1", "name": "Published form", "status": "ACTIVE"}]}),
        "/act_123/campaigns": (403, {"error": {"message": "Permission denied", "type": "OAuthException", "code": 200}}),
        "/act_123/adsets": (200, {"data": []}),
        "/act_123/ads": (200, {"data": []}),
    }

    result = _run_discovery(
        monkeypatch, responses, page_id="page-1", ad_account_id="123",
    )

    assert result["pages"][0]["id"] == "page-1"
    assert result["lead_forms"][0]["id"] == "form-1"
    assert result["campaigns"] == []
    assert "still connect using the Page and Lead Form" in result["warnings"][0]
