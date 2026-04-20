"""Tests de app.integrations.sentry."""

from __future__ import annotations

import sys
from unittest import mock

import pytest

import app.integrations.sentry as sentry_mod
from app.core.config import reset_settings_cache


@pytest.fixture(autouse=True)
def _reset_state():
    sentry_mod._initialized = False
    reset_settings_cache()
    yield
    sentry_mod._initialized = False
    reset_settings_cache()


def test_no_op_when_dsn_empty():
    assert sentry_mod.init_sentry() is False


def test_no_op_when_sdk_missing(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
    reset_settings_cache()
    # Simule sentry_sdk introuvable
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    assert sentry_mod.init_sentry() is False


def test_init_calls_sdk_when_available(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    reset_settings_cache()

    fake_sdk = mock.MagicMock()
    fake_flask = mock.MagicMock()
    fake_integrations_flask = mock.MagicMock(FlaskIntegration=fake_flask)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.flask", fake_integrations_flask)

    assert sentry_mod.init_sentry() is True
    fake_sdk.init.assert_called_once()
    kwargs = fake_sdk.init.call_args.kwargs
    assert kwargs["dsn"] == "https://x@sentry.io/1"
    assert kwargs["environment"] == "staging"
    assert kwargs["send_default_pii"] is False


def test_init_is_idempotent(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
    reset_settings_cache()
    fake_sdk = mock.MagicMock()
    fake_integrations_flask = mock.MagicMock(FlaskIntegration=mock.MagicMock())
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.flask", fake_integrations_flask)

    assert sentry_mod.init_sentry() is True
    assert sentry_mod.init_sentry() is True
    assert fake_sdk.init.call_count == 1
