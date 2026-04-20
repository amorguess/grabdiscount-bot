"""Tests de app.core.config."""

from __future__ import annotations

import pytest

from app.core.config import get_settings, reset_settings_cache
from app.core.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_get_settings_success():
    s = get_settings()
    assert s.telegram.bot_token == "test-token"
    assert s.telegram.admin_chat_id == 123
    assert s.telegram.channel_id == -100123456789
    assert s.dashboard.password == "test-pwd"
    assert s.dashboard.secret == "test-secret-32-chars-minimum-abcdef"
    assert s.dashboard.port == 5001


def test_get_settings_is_cached():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_reset_settings_cache(monkeypatch):
    s1 = get_settings()
    reset_settings_cache()
    monkeypatch.setenv("DASHBOARD_PORT", "6000")
    s2 = get_settings()
    assert s1 is not s2
    assert s2.dashboard.port == 6000


def test_missing_bot_token_raises(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN")
    reset_settings_cache()
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        get_settings()


def test_missing_dashboard_secret_raises(monkeypatch):
    monkeypatch.delenv("DASHBOARD_SECRET")
    reset_settings_cache()
    with pytest.raises(ConfigError, match="DASHBOARD_SECRET"):
        get_settings()


def test_admin_chat_id_not_int_raises(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "not-a-number")
    reset_settings_cache()
    with pytest.raises(ConfigError, match="ADMIN_CHAT_ID"):
        get_settings()


def test_dashboard_port_not_int_raises(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "abc")
    reset_settings_cache()
    with pytest.raises(ConfigError, match="DASHBOARD_PORT"):
        get_settings()


def test_employee_password_defaults_to_admin(monkeypatch):
    monkeypatch.delenv("EMPLOYEE_PASSWORD")
    reset_settings_cache()
    s = get_settings()
    assert s.dashboard.employee_password == s.dashboard.password


def test_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings_cache()
    s = get_settings()
    assert s.data_dir == tmp_path
    assert s.data_path("accounts.json") == tmp_path / "accounts.json"


def test_monitoring_disabled_when_no_dsn():
    s = get_settings()
    assert s.monitoring.enabled is False


def test_monitoring_enabled_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.io/1")
    reset_settings_cache()
    s = get_settings()
    assert s.monitoring.enabled is True
    assert s.monitoring.sentry_dsn == "https://abc@sentry.io/1"


def test_settings_are_frozen():
    s = get_settings()
    with pytest.raises((AttributeError, TypeError)):
        s.data_dir = "/tmp"  # type: ignore[misc]
