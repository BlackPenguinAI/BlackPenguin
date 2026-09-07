from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.middleware import MultiTenantMiddleware
from app.modules.health.router import router as health_router


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MultiTenantMiddleware)
    app.include_router(health_router, prefix=f"{settings.API_V1_STR}/health")

    @app.get(f"{settings.API_V1_STR}/protected")
    def protected_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get(f"{settings.API_V1_STR}/projects/integrations/meta/oauth/callback")
    def meta_oauth_callback() -> dict[str, bool]:
        return {"ok": True}

    @app.get(f"{settings.API_V1_STR}/webhooks/meta")
    def meta_webhook_verify() -> dict[str, bool]:
        return {"ok": True}

    @app.post(f"{settings.API_V1_STR}/webhooks/meta")
    def meta_webhook_delivery() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_health_version_is_public_without_jwt():
    with TestClient(build_test_app()) as client:
        response = client.get(f"{settings.API_V1_STR}/health/version")

    assert response.status_code == 200
    assert response.json()["commit"] == settings.APP_COMMIT_SHA


def test_health_readiness_reaches_endpoint_without_jwt():
    with patch(
        "app.modules.health.router.engine.connect",
        side_effect=RuntimeError("database unavailable during test"),
    ):
        with TestClient(build_test_app()) as client:
            response = client.get(f"{settings.API_V1_STR}/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "reason": "database_unavailable",
    }


def test_health_readiness_does_not_expose_schema_details():
    connection_context = MagicMock()
    connection = connection_context.__enter__.return_value
    inspector = MagicMock()
    inspector.has_table.return_value = False

    with (
        patch(
            "app.modules.health.router.engine.connect",
            return_value=connection_context,
        ),
        patch("app.modules.health.router.inspect", return_value=inspector),
    ):
        with TestClient(build_test_app()) as client:
            response = client.get(f"{settings.API_V1_STR}/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "reason": "schema_incompatible",
    }
    connection.execute.assert_called_once()


def test_application_route_remains_protected_without_jwt():
    with TestClient(build_test_app()) as client:
        response = client.get(f"{settings.API_V1_STR}/protected")

    assert response.status_code == 401


def test_meta_provider_callbacks_are_public_without_exposing_other_project_routes():
    with TestClient(build_test_app()) as client:
        oauth = client.get(f"{settings.API_V1_STR}/projects/integrations/meta/oauth/callback")
        webhook_verify = client.get(f"{settings.API_V1_STR}/webhooks/meta")
        webhook_delivery = client.post(f"{settings.API_V1_STR}/webhooks/meta")
        protected = client.get(f"{settings.API_V1_STR}/projects/project-1/meta/oauth/start")

    assert oauth.status_code == 200
    assert webhook_verify.status_code == 200
    assert webhook_delivery.status_code == 200
    assert protected.status_code == 401
