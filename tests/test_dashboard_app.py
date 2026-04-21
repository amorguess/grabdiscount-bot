"""Tests du factory Flask + enregistrement des blueprints."""

from __future__ import annotations

from app.core.config import get_settings, reset_settings_cache
from app.dashboard.app import create_app


def test_create_app_returns_flask_instance() -> None:
    reset_settings_cache()
    app = create_app(config_overrides={"TESTING": True})
    assert app.name == "grabdiscount.dashboard"
    assert app.config["TESTING"] is True
    assert app.config["SECRET_KEY"] == "test-secret-32-chars-minimum-abcdef"


def test_api_blueprints_registered() -> None:
    reset_settings_cache()
    app = create_app()
    assert "health" in app.blueprints
    assert "restaurants" in app.blueprints


def test_health_endpoint_responds_200() -> None:
    reset_settings_cache()
    app = create_app(config_overrides={"TESTING": True})
    with app.test_client() as c:
        resp = c.get("/api/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "version" in body


def test_settings_injection() -> None:
    """Les settings injectés l'emportent sur le singleton global."""
    reset_settings_cache()
    custom = get_settings()
    app = create_app(settings=custom)
    assert app.config["SETTINGS"] is custom
