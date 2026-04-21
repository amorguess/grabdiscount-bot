"""Tests du blueprint auth (`/login`, `/logout`, `/api/auth/status`)."""

from __future__ import annotations

import pytest

from app.core.config import reset_settings_cache
from app.dashboard.app import create_app


@pytest.fixture
def app():
    reset_settings_cache()
    return create_app(config_overrides={"TESTING": True})


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


# ─── Login OK ─────────────────────────────────────────────────────────


def test_login_success_form(client):
    resp = client.post("/login", data={"password": "test-pwd"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert sess.get("ok") is True


def test_login_success_json(client):
    resp = client.post(
        "/login",
        json={"password": "test-pwd"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ─── Login KO ─────────────────────────────────────────────────────────


def test_login_wrong_password_returns_401(client):
    resp = client.post("/login", json={"password": "bad"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_password"


def test_login_empty_password_returns_401(client):
    resp = client.post("/login", json={})
    assert resp.status_code == 401


# ─── Rate limit ───────────────────────────────────────────────────────


def test_login_rate_limit_after_5_failures(app, client):
    for _ in range(5):
        resp = client.post("/login", json={"password": "bad"})
        assert resp.status_code == 401

    resp = client.post("/login", json={"password": "bad"})
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "rate_limited"


def test_login_rate_limit_does_not_apply_to_success_after_reset(app, client):
    """Après un login réussi, le compteur est reset → pas de rate limit."""
    for _ in range(3):
        client.post("/login", json={"password": "bad"})

    # Succès : reset du compteur
    resp = client.post("/login", json={"password": "test-pwd"})
    assert resp.status_code == 200

    # Après logout + 3 échecs à nouveau → toujours pas bloqué (on est à 3/5)
    client.post("/logout")
    for _ in range(4):
        resp = client.post("/login", json={"password": "bad"})
        assert resp.status_code == 401


# ─── Logout ───────────────────────────────────────────────────────────


def test_logout_clears_session(client):
    client.post("/login", json={"password": "test-pwd"})
    resp = client.post("/logout", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("ok") is None


def test_logout_redirects_for_browser(client):
    client.post("/login", data={"password": "test-pwd"})
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ─── Auth status ──────────────────────────────────────────────────────


def test_auth_status_anonymous(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}


def test_auth_status_authenticated(client):
    client.post("/login", json={"password": "test-pwd"})
    resp = client.get("/api/auth/status")
    assert resp.get_json() == {"authenticated": True}
