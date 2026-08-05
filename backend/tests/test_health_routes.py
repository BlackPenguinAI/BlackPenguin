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
